"""Доска «2× откат»: история до 7d, липкий список, LH, OI↓, EMA."""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from signal_engine.ema_breakdown import ema_breakdown_by_interval
from signal_engine.evaluate import Reading, evaluate
from signal_engine.pump_history import HistoryPump, history_pump_metrics
from signal_engine.pump_scan import price_24h_pct
from signal_engine.stage_debounce import resolve_stage
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import (
    TwoPeakMatch,
    absolute_high_since,
    closed_bars,
    find_two_peak_htf,
    lower_high_chain_count,
)
from signal_engine.watch_store import WatchRow, WatchStore

BOARD_ID = "x2_retrace"

_MS_24H = 24 * 3600 * 1000
_MS_7D = 7 * 24 * 3600 * 1000
_MS_1H = 3600 * 1000


def _resolve_last_price(state: SymbolState) -> float | None:
    if state.last_price is not None and state.last_price > 0:
        return float(state.last_price)
    for key in ("60", "240", "15", "30"):
        bars = state.bars_htf.get(key) or []
        if bars:
            return float(bars[-1].close)
    if state.bars_1m:
        return float(state.bars_1m[-1].close)
    return None


def _meets_x2_turnover(state: SymbolState) -> bool:
    turnover = state.turnover_24h_usdt
    if turnover is None or turnover < config.X2_RETRACE_MIN_TURNOVER_24H_USDT:
        return False
    return True


def _eligible(state: SymbolState) -> bool:
    if not _meets_x2_turnover(state):
        return False
    price = _resolve_last_price(state)
    if price is None or price <= 0:
        return False
    return True


def price_change_7d_pct(state: SymbolState, now_ms: int) -> float | None:
    """Изменение close за 7 суток (закрытые свечи 1D или 1H)."""
    for interval, min_bars, lookback in (("D", 8, 7), ("60", 7 * 24 + 2, 7 * 24)):
        bars = state.bars_htf.get(interval) or []
        closed = closed_bars(bars, interval, now_ms)
        if len(closed) < min_bars:
            continue
        ref = closed[-lookback - 1].close
        cur = closed[-1].close
        if ref <= 0 or cur <= 0:
            continue
        return (cur - ref) / ref * 100.0
    price = _resolve_last_price(state)
    if price is None:
        return None
    bars_1h = closed_bars(state.bars_htf.get("60") or [], "60", now_ms)
    if len(bars_1h) < 2:
        return None
    ref_ts = now_ms - _MS_7D
    ref_close: float | None = None
    for bar in bars_1h:
        if bar.timestamp <= ref_ts:
            ref_close = float(bar.close)
        else:
            break
    if ref_close is None or ref_close <= 0:
        ref_close = float(bars_1h[0].close)
    return (price - ref_close) / ref_close * 100.0


def _pump_leg_volume_spike_ok(bars_1h: list[Bar], valley_ts: int, now_ms: int) -> bool:
    """Обязательный всплеск объёма на участке роста до абсолютного пика 1H."""
    closed = closed_bars(bars_1h, "60", now_ms)
    leg = [b for b in closed if b.timestamp >= valley_ts]
    if len(leg) < 3:
        return False
    peak_i = max(range(len(leg)), key=lambda i: leg[i].high)
    growth = leg[: peak_i + 1]
    if len(growth) < 2:
        return False
    vols = [float(b.volume) for b in growth]
    peak_vol = max(vols)
    pre = [b for b in closed if b.timestamp < valley_ts]
    if len(pre) >= 2:
        tail = pre[-5:]
        baseline = sum(float(b.volume) for b in tail) / len(tail)
    else:
        head = vols[: max(1, len(vols) // 2)]
        baseline = sum(head) / len(head)
    if baseline <= 0:
        return False
    return peak_vol / baseline >= config.X2_RETRACE_PUMP_VOLUME_SPIKE_MIN


def _entry_quality_ok(
    state: SymbolState,
    now_ms: int,
    hist: HistoryPump,
    two_peak: TwoPeakMatch | None,
    bars_1h: list[Bar],
) -> bool:
    if two_peak is None:
        return False
    pct7 = price_change_7d_pct(state, now_ms)
    if pct7 is None or pct7 < config.X2_RETRACE_MIN_PRICE_CHANGE_7D_PCT:
        return False
    if not _pump_leg_volume_spike_ok(bars_1h, hist.valley_ts, now_ms):
        return False
    return True


def _pullback_pct(
    bars_1h: list[Bar],
    pump_start_ts: int,
    now_ms: int,
    last_price: float,
) -> tuple[bool, float]:
    peak = absolute_high_since(bars_1h, pump_start_ts, "60", now_ms)
    if peak is None:
        return False, 0.0
    abs_high, _high_ts = peak
    if abs_high <= 0:
        return False, 0.0
    drop = (abs_high - last_price) / abs_high * 100.0
    if drop < config.X2_RETRACE_MIN_PULLBACK_PCT:
        return False, drop
    closed = closed_bars(bars_1h, "60", now_ms)
    recent = [b for b in closed if b.timestamp >= now_ms - _MS_24H]
    if len(recent) < 1:
        return False, drop
    high_24h = max(b.high for b in recent)
    if last_price >= high_24h * 0.998:
        return False, drop
    return True, drop


def _ema_depth_max(ema_map: dict[str, dict]) -> int:
    if not ema_map:
        return 0
    return max(int(item.get("depth") or 0) for item in ema_map.values())


def candidate_stage(
    *,
    peak_mult: float,
    pullback_ok: bool,
    two_peak: TwoPeakMatch | None,
    lh_1h: int,
    lh_4h: int,
    oi_drop: bool,
    ema_depth: int,
) -> int:
    if peak_mult < config.X2_RETRACE_MIN_MULTIPLIER:
        return 0
    if two_peak is None:
        return 0
    if not pullback_ok:
        return 1
    lh_ok = two_peak is not None or lh_1h >= 1 or lh_4h >= 1
    if not lh_ok:
        return 2
    if oi_drop and ema_depth >= 2:
        return 4
    if oi_drop or ema_depth >= 1:
        return 3
    return 2


@dataclass
class X2RetraceItem:
    symbol: str
    stage: int
    multiplier: float
    peak_mult: float
    min_low_5d: float
    pump_start_ts: int
    pullback_pct: float
    lh_1h: int
    lh_4h: int
    last_price: float
    price_24h_pct: float | None
    turnover_24h_usdt: float
    oi_drop: bool
    oi_change_pct: float | None
    ema_depth: int
    two_peak_kind: str | None = None
    two_peak_tf: str | None = None
    two_peak_bars_between: int | None = None
    pending_stage: int | None = None
    ema_by_tf: dict[str, dict] = field(default_factory=dict)
    updated_at: int = 0

    def to_data(self) -> dict:
        col = config.X2_RETRACE_COLUMNS[self.stage]
        return {
            "symbol": self.symbol,
            "stage": self.stage,
            "color": col["color"],
            "status": col["status"],
            "label": col["label"],
            "multiplier": round(self.multiplier, 2),
            "peak_mult": round(self.peak_mult, 2),
            "min_low_5d": self.min_low_5d,
            "pump_start_ts": self.pump_start_ts,
            "pullback_pct": round(self.pullback_pct, 2),
            "lh_1h": self.lh_1h,
            "lh_4h": self.lh_4h,
            "last_price": self.last_price,
            "price_24h_pct": round(self.price_24h_pct, 2) if self.price_24h_pct is not None else None,
            "turnover_24h_usdt": self.turnover_24h_usdt,
            "oi_drop": self.oi_drop,
            "oi_change_pct": self.oi_change_pct,
            "ema_depth": self.ema_depth,
            "two_peak_kind": self.two_peak_kind,
            "two_peak_tf": self.two_peak_tf,
            "two_peak_bars_between": self.two_peak_bars_between,
            "pending_stage": self.pending_stage,
            "ema_by_tf": self.ema_by_tf,
            "updated_at": self.updated_at,
        }


def _continued_pump(meta: dict, hist: HistoryPump | None) -> bool:
    if hist is None:
        return False
    latched = float(meta.get("peak_mult") or 0)
    return latched > 0 and hist.peak_mult >= latched * 1.08


def _metrics_for_state(state: SymbolState, now_ms: int, meta: dict) -> tuple[X2RetraceItem, bool] | None:
    hist = history_pump_metrics(state, now_ms)
    if hist is None:
        return None
    pump_start = int(meta.get("valley_ts") or hist.valley_ts)
    min_low = float(meta.get("min_low") or hist.min_low)
    peak_mult = max(float(meta.get("peak_mult") or 0), hist.peak_mult)
    bars_1h = state.bars_htf.get("60") or []
    bars_4h = state.bars_htf.get("240") or []
    lh_1h = lower_high_chain_count(bars_1h, pump_start, "60", now_ms, config.X2_RETRACE_PIVOT_WING)
    lh_4h = lower_high_chain_count(bars_4h, pump_start, "240", now_ms, config.X2_RETRACE_PIVOT_WING)
    two_peak = find_two_peak_htf(bars_1h, bars_4h, pump_start, now_ms)
    pullback_ok, pullback_pct = _pullback_pct(bars_1h, pump_start, now_ms, float(state.last_price))
    reading: Reading = evaluate(state, now_ms)
    ema_map = ema_breakdown_by_interval(state.bars_htf)
    ema_depth = _ema_depth_max(ema_map)
    pct24 = price_24h_pct(state.price_24h_change)
    item = X2RetraceItem(
        symbol=state.symbol,
        stage=1,
        multiplier=hist.current_mult,
        peak_mult=peak_mult,
        min_low_5d=min_low,
        pump_start_ts=pump_start,
        pullback_pct=pullback_pct,
        lh_1h=lh_1h,
        lh_4h=lh_4h,
        last_price=float(state.last_price),
        price_24h_pct=pct24,
        turnover_24h_usdt=float(state.turnover_24h_usdt or 0),
        oi_drop=reading.oi_drop,
        oi_change_pct=reading.oi_change_pct,
        ema_depth=ema_depth,
        two_peak_kind=two_peak.kind if two_peak else None,
        two_peak_tf=_interval_label(two_peak.interval) if two_peak else None,
        two_peak_bars_between=two_peak.bars_between if two_peak else None,
        ema_by_tf=ema_map,
        updated_at=now_ms,
    )
    return item, pullback_ok, two_peak


def _interval_label(code: str) -> str:
    return {"60": "1H", "240": "4H", "D": "1D"}.get(code, code)


def _should_exit_watch(state: SymbolState, meta: dict, now_ms: int) -> bool:
    """Откат часто с красным 24h — снимаем, только если памп сдулся к дну."""
    hist = history_pump_metrics(state, now_ms)
    if hist is None:
        return False
    min_low = float(meta.get("min_low") or hist.min_low)
    price = _resolve_last_price(state)
    if price is None or min_low <= 0:
        return False
    if price < min_low * config.X2_RETRACE_EXIT_NEAR_VALLEY_MULT:
        return True
    if hist.current_mult < config.X2_RETRACE_EXIT_MIN_CURRENT_MULT:
        return True
    return False


def build_x2_retrace_board(states: dict[str, SymbolState], now_ms: int, watches: WatchStore) -> dict:
    active = watches.active(BOARD_ID)
    for symbol, state in states.items():
        if not _eligible(state):
            continue
        if symbol in active:
            continue
        prior = watches.get(BOARD_ID, symbol)
        if prior is not None and prior.dismissed:
            continue
        hist = history_pump_metrics(state, now_ms)
        if hist is None:
            continue
        pump_start = hist.valley_ts
        bars_1h = state.bars_htf.get("60") or []
        bars_4h = state.bars_htf.get("240") or []
        two_peak = find_two_peak_htf(bars_1h, bars_4h, pump_start, now_ms)
        if not _entry_quality_ok(state, now_ms, hist, two_peak, bars_1h):
            continue
        watch = WatchRow(
            board=BOARD_ID,
            symbol=symbol,
            entered_at=now_ms,
            dismissed=False,
            confirmed_stage=1,
            pending_stage=None,
            pending_since=None,
            meta={
                "min_low": hist.min_low,
                "peak_mult": hist.peak_mult,
                "valley_ts": hist.valley_ts,
                "interval": hist.interval,
            },
        )
        watches.upsert(watch)
        active[symbol] = watch

    items: list[X2RetraceItem] = []
    for symbol, watch in list(active.items()):
        state = states.get(symbol)
        if state is None:
            watches.remove(BOARD_ID, symbol)
            continue
        price = _resolve_last_price(state)
        if price is None:
            continue
        if state.last_price is None or state.last_price <= 0:
            state.last_price = price
        if not _meets_x2_turnover(state):
            watches.remove(BOARD_ID, symbol)
            continue
        if _should_exit_watch(state, watch.meta, now_ms):
            watches.remove(BOARD_ID, symbol)
            continue
        measured = _metrics_for_state(state, now_ms, watch.meta)
        if measured is None:
            continue
        row, pullback_ok, two_peak = measured
        hist_live = history_pump_metrics(state, now_ms)
        bars_1h = state.bars_htf.get("60") or []
        if hist_live is None or not _entry_quality_ok(state, now_ms, hist_live, two_peak, bars_1h):
            watches.remove(BOARD_ID, symbol)
            continue
        watch.meta["peak_mult"] = max(float(watch.meta.get("peak_mult") or 0), row.peak_mult)
        watch.meta["min_low"] = row.min_low_5d
        watch.meta["valley_ts"] = row.pump_start_ts
        cand = candidate_stage(
            peak_mult=row.peak_mult,
            pullback_ok=pullback_ok,
            two_peak=two_peak,
            lh_1h=row.lh_1h,
            lh_4h=row.lh_4h,
            oi_drop=row.oi_drop,
            ema_depth=row.ema_depth,
        )
        hist = history_pump_metrics(state, now_ms)
        confirmed, pending, pending_since = resolve_stage(
            confirmed=watch.confirmed_stage,
            candidate=cand,
            pending_stage=watch.pending_stage,
            pending_since=watch.pending_since,
            now_ms=now_ms,
            continued_pump=_continued_pump(watch.meta, hist),
        )
        watch.confirmed_stage = confirmed
        watch.pending_stage = pending
        watch.pending_since = pending_since
        watches.upsert(watch)
        row.stage = confirmed
        row.pending_stage = pending
        items.append(row)

    grouped: dict[int, list[X2RetraceItem]] = {s: [] for s in (1, 2, 3, 4)}
    for item in items:
        grouped[item.stage].append(item)
    columns = []
    for stage in (4, 3, 2, 1):
        col = config.X2_RETRACE_COLUMNS[stage]
        ordered = sorted(
            grouped[stage],
            key=lambda row: (row.peak_mult, row.lh_1h + row.lh_4h, row.ema_depth),
            reverse=True,
        )
        columns.append({**col, "stage": stage, "signals": [row.to_data() for row in ordered]})
    return {"type": "x2_retrace_board", "timestamp": now_ms, "data": {"columns": columns}}
