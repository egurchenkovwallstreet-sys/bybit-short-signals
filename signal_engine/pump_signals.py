"""Доска «Памп сигналы»: зелёная / жёлтая / красная / фиолетовая колонки."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import config
from signal_engine.evaluate import evaluate as evaluate_reading
from signal_engine.flow import taker_sellers_control
from signal_engine.paper.detect import (
    MANDATORY,
    PumpInfo,
    find_pump,
    merged_15m,
    paper_entry_blocks,
    paper_t20_p10_tri_blocks,
)
from signal_engine.paper.tape import SymbolTape
from signal_engine.pump_scan import _weakening_score
from signal_engine.pump_phases import drawdown_from_peak_pct
from signal_engine.pump_unified import detect_unified_episode, symbol_has_unified_pump
from signal_engine.stage_debounce import resolve_stage
from signal_engine.watch_store import WatchRow, WatchStore

if TYPE_CHECKING:
    from signal_engine.paper.strategy import PaperStrategy
    from signal_engine.state import SymbolState

BOARD_ID = "pump_signals"
MSK = ZoneInfo("Europe/Moscow")
MIN_MS = 60_000

COLUMN_RED = "red"
COLUMN_YELLOW = "yellow"
COLUMN_GREEN = "green"
COLUMN_PURPLE = "purple"
_COLUMN_RANK = {
    COLUMN_RED: 1,
    COLUMN_YELLOW: 2,
    COLUMN_GREEN: 3,
    COLUMN_PURPLE: 4,
}
_RANK_COLUMN = {
    1: COLUMN_RED,
    2: COLUMN_YELLOW,
    3: COLUMN_GREEN,
    4: COLUMN_PURPLE,
}


def should_remove_pump_signal(
    state: SymbolState,
    peak_price: float,
    *,
    now_ms: int | None = None,
    peak_ts: int | None = None,
    entered_at: int | None = None,
) -> bool:
    """Снять с доски: глубокий откат, протухший эпизод или долго без хая."""
    if peak_price <= 0:
        return False
    price = state.last_price
    if price is None or price <= 0:
        return False
    dd = drawdown_from_peak_pct(price, peak_price)
    if dd >= config.PUMP_SIGNALS_REMOVE_DRAWDOWN_PCT:
        return True
    if now_ms is None:
        return False
    max_days = int(config.PUMP_SIGNALS_MAX_EPISODE_DAYS)
    if entered_at and now_ms - entered_at >= max_days * 24 * 3_600_000:
        return True
    if peak_ts:
        stale_h = int(config.PUMP_SIGNALS_STALE_HOURS_NO_HIGH)
        stale_dd = float(config.PUMP_SIGNALS_STALE_MIN_DRAWDOWN_PCT)
        mins_no_high = _minutes_no_new_high(
            state, peak_ts, now_ms, peak_price=peak_price
        )
        if mins_no_high >= stale_h * 60 and dd >= stale_dd:
            return True
    return False


def is_purple_drawdown(drawdown: float | None) -> bool:
    if drawdown is None:
        return False
    lo = config.PUMP_SIGNALS_PURPLE_MIN_DRAWDOWN_PCT
    hi = config.PUMP_SIGNALS_PURPLE_MAX_DRAWDOWN_PCT
    # Зелёная колонка держит откат до 15% включительно; фиолетовая — строго выше.
    return drawdown > lo and drawdown < hi


def fmt_msk(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=MSK).strftime("%d.%m.%Y %H:%M")


def elapsed_label(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    m = int(max(0, minutes))
    if m < 60:
        return f"{m} мин"
    h, r = divmod(m, 60)
    if r == 0:
        return f"{h} ч"
    return f"{h} ч {r} мин"


def _passed_nine(checks: dict[str, dict]) -> int:
    return sum(1 for key in MANDATORY if (checks.get(key) or {}).get("ok"))


def _episode_high_7d(state: SymbolState, now_ms: int) -> tuple[float, int] | None:
    """Max high на 1h за окно PUMP_UNIFIED_VALLEY_LOOKBACK_DAYS (истинный пик long-пампа)."""
    from signal_engine.swing_highs import closed_bars

    lookback = int(config.PUMP_UNIFIED_VALLEY_LOOKBACK_DAYS) * 24 * 3_600_000
    bars_1h = closed_bars(state.bars_htf.get("60") or [], "60", now_ms)
    recent = [b for b in bars_1h if now_ms - lookback <= b.timestamp <= now_ms]
    if not recent:
        return None
    peak_bar = max(recent, key=lambda b: b.high)
    if peak_bar.high <= 0:
        return None
    return float(peak_bar.high), int(peak_bar.timestamp)


def lock_m15_peak_at_entry(
    state: SymbolState,
    draft: Any,
    now_ms: int,
) -> tuple[float, int]:
    """Пик эпизода: max(7d/1h, unified draft, 15m от впадины) — не локальный отскок после обвала."""
    ep_p = float(draft.peak_price or 0)
    ep_t = int(draft.peak_ts or 0)
    hi_7d = _episode_high_7d(state, now_ms)
    if hi_7d and hi_7d[0] > ep_p:
        ep_p, ep_t = hi_7d

    bars = merged_15m(state)
    valley_ts = int(draft.valley_ts)
    m15_p, m15_t = ep_p, ep_t
    if bars:
        window = [b for b in bars if valley_ts <= b.timestamp <= now_ms]
        if not window:
            window = [b for b in bars if b.timestamp <= now_ms][-48:]
        if window:
            peak_bar = max(window, key=lambda b: b.high)
            m15_p, m15_t = float(peak_bar.high), int(peak_bar.timestamp)
    if ep_p >= m15_p:
        return ep_p, ep_t
    return m15_p, m15_t


def _reconcile_peak_with_episode(
    watch: WatchRow,
    state: SymbolState,
    now_ms: int,
    fixed_p: float,
    fixed_ts: int,
) -> tuple[float, int]:
    """Поднять зафиксированный пик, если 7d-high выше (legacy watch после обвала)."""
    hi = _episode_high_7d(state, now_ms)
    if hi is None:
        return fixed_p, fixed_ts
    h_p, h_t = hi
    if h_p > fixed_p * 1.02:
        watch.meta["m15_peak_price"] = h_p
        watch.meta["m15_peak_ts"] = h_t
        return h_p, h_t
    return fixed_p, fixed_ts


def _watch_fixed_peak(watch: WatchRow) -> tuple[float, int] | None:
    raw_p = watch.meta.get("m15_peak_price")
    raw_t = watch.meta.get("m15_peak_ts")
    if raw_p is None or raw_t is None:
        return None
    p = float(raw_p)
    t = int(raw_t)
    if p <= 0 or t <= 0:
        return None
    return p, t


def _pump_from_watch(
    watch: WatchRow,
    fixed_p: float,
    fixed_ts: int,
) -> PumpInfo:
    """Карточка на доске: не снимать, если find_pump временно не видит 15m."""
    valley_ts = int(watch.meta.get("valley_ts") or fixed_ts)
    valley_p = float(watch.meta.get("valley_price") or fixed_p)
    growth = watch.meta.get("growth_pct_lock")
    if growth is None and valley_p > 0:
        growth = (fixed_p / valley_p - 1.0) * 100.0
    trigger = str(watch.meta.get("trigger") or watch.meta.get("pump_class") or "watch")
    return PumpInfo(
        kind="short",
        trigger=trigger,
        growth_pct=float(growth or 0),
        valley_price=valley_p,
        valley_ts=valley_ts,
        peak_price=fixed_p,
        peak_ts=fixed_ts,
        growth={},
    )


def _ensure_fixed_peak(
    watch: WatchRow,
    state: SymbolState,
    now_ms: int,
) -> tuple[float, int]:
    fixed = _watch_fixed_peak(watch)
    if fixed is not None:
        return fixed
    bars = merged_15m(state)
    valley_ts = int(watch.meta.get("valley_ts") or 0)
    fallback_p = float(watch.meta.get("peak_price") or 0)
    if bars and valley_ts > 0:
        window = [b for b in bars if valley_ts <= b.timestamp <= now_ms]
        if window:
            pb = max(window, key=lambda b: b.high)
            watch.meta["m15_peak_price"] = float(pb.high)
            watch.meta["m15_peak_ts"] = int(pb.timestamp)
            return float(pb.high), int(pb.timestamp)
    if fallback_p > 0:
        ts = int(watch.meta.get("m15_peak_ts") or watch.entered_at or now_ms)
        watch.meta["m15_peak_price"] = fallback_p
        watch.meta["m15_peak_ts"] = ts
        return fallback_p, ts
    return 0.0, 0


def _minutes_no_new_high(
    state: SymbolState,
    peak_ts: int,
    now_ms: int,
    *,
    peak_price: float | None = None,
) -> float | None:
    """Минут с последнего обновления хая (не выше зафиксированного M15-пика)."""
    cap = float(peak_price) if peak_price and peak_price > 0 else None
    session_high = cap or 0.0
    hi_ts = peak_ts
    for bar in state.bars_1m:
        if bar.timestamp < peak_ts:
            continue
        if bar.high > session_high + 1e-12:
            if cap is not None and bar.high > cap + 1e-12:
                continue
            session_high = bar.high
            hi_ts = bar.timestamp
    if session_high <= 0 or (cap and session_high + 1e-12 < cap * 0.999):
        for bar in merged_15m(state):
            if bar.timestamp < peak_ts:
                continue
            if bar.high > session_high + 1e-12:
                if cap is not None and bar.high > cap + 1e-12:
                    continue
                session_high = bar.high
                hi_ts = bar.timestamp
    if session_high <= 0:
        return None
    last = float(state.last_price or 0)
    if cap and last > cap + 1e-12:
        last = cap
    if cap and last >= cap * 0.999:
        hi_ts = max(hi_ts, now_ms - 60_000)
    elif last >= session_high * 0.999:
        hi_ts = max(hi_ts, now_ms - 60_000)
    return max(0.0, (now_ms - hi_ts) / MIN_MS)


def _pump_still_active(
    drawdown: float | None,
    minutes_no_high: float | None,
    since_peak: float | None,
) -> bool:
    """Рост ещё идёт — не «памп прошёл» (фиолетовая)."""
    lo = config.PUMP_SIGNALS_PURPLE_MIN_DRAWDOWN_PCT
    if drawdown is not None and drawdown <= lo:
        return True
    min_no_high = config.PUMP_SIGNALS_PURPLE_MIN_MINUTES_NO_HIGH
    if minutes_no_high is not None and minutes_no_high < min_no_high:
        return True
    red_early = config.PUMP_SIGNALS_RED_MAX_SINCE_PEAK_MIN
    if since_peak is not None and since_peak < red_early:
        return True
    return False


def _purple_column_ok(
    drawdown: float | None,
    minutes_no_high: float | None,
    since_peak: float | None,
) -> bool:
    return is_purple_drawdown(drawdown) and not _pump_still_active(
        drawdown, minutes_no_high, since_peak
    )


def raw_column(
    *,
    checks: dict[str, dict],
    metrics: dict,
    reading,
    weaken: int,
    drawdown: float | None,
    since_peak: float | None,
    minutes_no_high: float | None,
) -> str:
    stall = bool((checks.get("stall") or {}).get("ok"))
    oi = bool((checks.get("oi_1h_negative") or {}).get("ok"))
    sells = bool((checks.get("sells_dominate") or {}).get("ok"))
    faded = bool((checks.get("buys_faded") or {}).get("ok"))
    vol_f = bool((checks.get("volume_fade") or {}).get("ok"))
    liq = bool((checks.get("short_liq_faded") or {}).get("ok"))
    p9 = _passed_nine(checks)
    gate = not paper_entry_blocks(metrics)
    tri = not paper_t20_p10_tri_blocks(metrics, checks)
    cvd = bool(reading.cvd_divergence)
    taker_sell = taker_sellers_control(reading.taker_ratio)

    green_dd_max = config.PUMP_SIGNALS_GREEN_MAX_DRAWDOWN_PCT
    green_dd_min = config.PUMP_SIGNALS_GREEN_MIN_DRAWDOWN_PCT
    if (
        gate
        and tri
        and stall
        and oi
        and (sells or vol_f)
        and liq
        and (faded or sells)
        and p9 >= config.PUMP_SIGNALS_GREEN_MIN_PASSED
        and drawdown is not None
        and green_dd_min <= drawdown <= green_dd_max
        and since_peak is not None
        and config.PAPER_ENTRY_SINCE_PEAK_MIN <= since_peak <= config.PAPER_ENTRY_SINCE_PEAK_MAX
    ):
        return COLUMN_GREEN
    if _purple_column_ok(drawdown, minutes_no_high, since_peak):
        return COLUMN_PURPLE

    red_min = config.PUMP_SIGNALS_RED_MAX_SINCE_PEAK_MIN
    if not stall and since_peak is not None and since_peak < red_min:
        return COLUMN_RED
    if minutes_no_high is not None and minutes_no_high < config.PAPER_STALL_MIN_MINUTES:
        if p9 < 5 or not stall:
            return COLUMN_RED
    if drawdown is not None and drawdown < 2.0 and not stall:
        return COLUMN_RED
    if weaken <= 1 and not stall and (reading.oi_change_1h_pct or 0) > 0:
        return COLUMN_RED

    return COLUMN_YELLOW


def _column_rank(name: str) -> int:
    return _COLUMN_RANK.get(name, 1)


def _rank_to_column(rank: int) -> str:
    return _RANK_COLUMN.get(rank, COLUMN_RED)


@dataclass
class PumpSignalCard:
    symbol: str
    column: str
    last_price: float
    growth_start_ts: int
    growth_start_msk: str
    elapsed_min: float
    growth_pct: float
    volume_ratio: float | None
    taker_buy_pct: float | None
    taker_sell_pct: float | None
    taker_ratio: float | None
    oi_1h_pct: float | None
    oi_4h_pct: float | None
    drawdown_pct: float | None
    since_peak_min: float | None
    passed_count: int
    weaken_score: int
    trigger: str
    cvd_divergence: bool
    updated_at: int
    turnover_24h_usdt: float | None = None
    peak_price_m15: float | None = None
    peak_ts_m15: int | None = None
    peak_msk: str = ""
    valley_price: float | None = None

    def to_data(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "column": self.column,
            "last_price": self.last_price,
            "peak_price_m15": self.peak_price_m15,
            "peak_ts_m15": self.peak_ts_m15,
            "peak_msk": self.peak_msk,
            "valley_price": self.valley_price,
            "growth_start_ts": self.growth_start_ts,
            "growth_start_msk": self.growth_start_msk,
            "elapsed_min": round(self.elapsed_min, 1),
            "elapsed_label": elapsed_label(self.elapsed_min),
            "growth_pct": round(self.growth_pct, 2),
            "volume_ratio": self.volume_ratio,
            "taker_buy_pct": self.taker_buy_pct,
            "taker_sell_pct": self.taker_sell_pct,
            "taker_ratio": self.taker_ratio,
            "oi_1h_pct": self.oi_1h_pct,
            "oi_4h_pct": self.oi_4h_pct,
            "drawdown_from_peak_pct": self.drawdown_pct,
            "since_peak_min": None if self.since_peak_min is None else round(self.since_peak_min),
            "passed_count": self.passed_count,
            "weaken_score": self.weaken_score,
            "trigger": self.trigger,
            "cvd_divergence": self.cvd_divergence,
            "updated_at": self.updated_at,
            "turnover_24h_usdt": self.turnover_24h_usdt,
        }


def _tape_for(paper: PaperStrategy | None, symbol: str) -> SymbolTape | None:
    if paper is None:
        return None
    return paper.tape.symbols.get(symbol)


def _klines_for(paper: PaperStrategy | None, symbol: str) -> dict:
    if paper is None:
        return {}
    return paper.klines.get(symbol, {})


def _taker_pcts(taker_ratio: float | None) -> tuple[float | None, float | None]:
    if taker_ratio is None or taker_ratio == float("inf"):
        return None, None
    buy_pct = round(taker_ratio / (1 + taker_ratio) * 100, 1) if taker_ratio >= 0 else None
    if buy_pct is None:
        return None, None
    return buy_pct, round(100 - buy_pct, 1)


def build_pump_signals_board(
    states: dict[str, SymbolState],
    now_ms: int,
    watches: WatchStore,
    paper: PaperStrategy | None = None,
) -> dict:
    active = watches.active(BOARD_ID)
    for symbol, state in states.items():
        if symbol in active:
            continue
        row = watches.get(BOARD_ID, symbol)
        if row is not None and row.dismissed:
            continue
        if not symbol_has_unified_pump(state, now_ms):
            continue
        draft = detect_unified_episode(state, now_ms)
        if draft is None:
            continue
        price = state.last_price
        if (
            price
            and draft.peak_price > 0
            and drawdown_from_peak_pct(float(price), float(draft.peak_price))
            >= config.PUMP_SIGNALS_REMOVE_DRAWDOWN_PCT
        ):
            continue
        m15_p, m15_t = lock_m15_peak_at_entry(state, draft, now_ms)
        if (
            price
            and m15_p > 0
            and drawdown_from_peak_pct(float(price), m15_p)
            >= config.PUMP_SIGNALS_REMOVE_DRAWDOWN_PCT
        ):
            continue
        row = WatchRow(
            board=BOARD_ID,
            symbol=symbol,
            entered_at=now_ms,
            dismissed=False,
            confirmed_stage=1,
            pending_stage=None,
            pending_since=None,
            meta={
                "m15_peak_price": m15_p,
                "m15_peak_ts": m15_t,
                "peak_price": m15_p,
                "valley_ts": draft.valley_ts,
                "valley_price": draft.valley_price,
                "growth_pct_lock": draft.growth_pct,
                "pump_class": draft.pump_class,
                "trigger": draft.pump_class,
                "column": COLUMN_RED,
            },
        )
        watches.upsert(row)
        active[symbol] = row

    cards: list[PumpSignalCard] = []
    for symbol, watch in list(active.items()):
        state = states.get(symbol)
        if state is None or state.last_price is None or state.last_price <= 0:
            continue
        fixed_p, fixed_ts = _ensure_fixed_peak(watch, state, now_ms)
        if fixed_p <= 0:
            continue
        fixed_p, fixed_ts = _reconcile_peak_with_episode(
            watch, state, now_ms, fixed_p, fixed_ts
        )
        peak = fixed_p
        if should_remove_pump_signal(
            state,
            peak,
            now_ms=now_ms,
            peak_ts=fixed_ts,
            entered_at=int(watch.entered_at or 0) or None,
        ):
            watches.remove(BOARD_ID, symbol)
            continue

        tape = _tape_for(paper, symbol)
        pump = find_pump(state, tape, now_ms)
        if pump is None:
            pump = _pump_from_watch(watch, fixed_p, fixed_ts)
        else:
            pump.peak_price = fixed_p
            pump.peak_ts = fixed_ts
            watch.meta["trigger"] = str(pump.trigger or watch.meta.get("trigger") or "")

        klines = _klines_for(paper, symbol)
        if not klines.get("15"):
            klines = {"15": merged_15m(state)}
        btc_pct = None
        from signal_engine.paper.detect import evaluate as eval_entry

        ev = eval_entry(state, tape or SymbolTape(), pump, klines, btc_pct, now_ms)
        reading = evaluate_reading(state, now_ms)
        weaken = _weakening_score(reading, now_ms, state)
        metrics = dict(ev.metrics)
        since_peak = (now_ms - fixed_ts) / MIN_MS
        metrics["since_peak_min"] = round(since_peak, 1)
        last = float(state.last_price or fixed_p)
        if fixed_p > 0:
            drawdown = max(0.0, (1.0 - min(last, fixed_p) / fixed_p) * 100.0)
            metrics["drawdown_from_peak_pct"] = round(drawdown, 2)
        else:
            drawdown = metrics.get("drawdown_from_peak_pct")
        minutes_no_high = _minutes_no_new_high(
            state, fixed_ts, now_ms, peak_price=fixed_p
        )
        dd_f = float(drawdown) if drawdown is not None else None
        candidate = raw_column(
            checks=ev.checks,
            metrics=metrics,
            reading=reading,
            weaken=weaken,
            drawdown=dd_f,
            since_peak=since_peak,
            minutes_no_high=minutes_no_high,
        )
        prev = str(watch.meta.get("column") or COLUMN_RED)
        purple_hold = _purple_column_ok(dd_f, minutes_no_high, since_peak)
        if prev == COLUMN_PURPLE and not purple_hold:
            confirmed_col = candidate
            pending = None
            pending_since = None
        else:
            confirmed_rank, pending, pending_since = resolve_stage(
                confirmed=_column_rank(prev),
                candidate=_column_rank(candidate),
                pending_stage=watch.pending_stage,
                pending_since=watch.pending_since,
                now_ms=now_ms,
                continued_pump=_pump_still_active(dd_f, minutes_no_high, since_peak),
            )
            confirmed_col = _rank_to_column(confirmed_rank)
        watch.confirmed_stage = confirmed_rank
        watch.pending_stage = pending
        watch.pending_since = pending_since
        watch.meta["column"] = confirmed_col
        watches.upsert(watch)

        buy_pct, sell_pct = _taker_pcts(reading.taker_ratio)
        valley_ts = int(watch.meta.get("valley_ts") or pump.valley_ts)
        elapsed = max(0.0, (now_ms - valley_ts) / MIN_MS)
        growth_lock = watch.meta.get("growth_pct_lock")
        growth_show = (
            float(growth_lock)
            if growth_lock is not None
            else float(pump.growth_pct)
        )
        valley_price = watch.meta.get("valley_price")
        tr = reading.taker_ratio
        turnover = state.turnover_24h_usdt
        vol_ratio = pump.volume_ratio
        if vol_ratio is None:
            vol_ratio = reading.volume_ratio
        if vol_ratio is None:
            raw_vr = metrics.get("volume_ratio_20m")
            if raw_vr is not None:
                vol_ratio = float(raw_vr)
        cards.append(
            PumpSignalCard(
                symbol=symbol,
                column=confirmed_col,
                last_price=float(state.last_price or fixed_p),
                growth_start_ts=valley_ts,
                growth_start_msk=fmt_msk(valley_ts),
                elapsed_min=elapsed,
                growth_pct=growth_show,
                peak_price_m15=fixed_p,
                peak_ts_m15=fixed_ts,
                peak_msk=fmt_msk(fixed_ts),
                valley_price=float(valley_price) if valley_price is not None else None,
                volume_ratio=vol_ratio,
                taker_buy_pct=buy_pct,
                taker_sell_pct=sell_pct,
                taker_ratio=round(tr, 3) if tr is not None else None,
                oi_1h_pct=reading.oi_change_1h_pct,
                oi_4h_pct=reading.oi_change_4h_pct,
                drawdown_pct=float(drawdown) if drawdown is not None else None,
                since_peak_min=since_peak,
                passed_count=ev.passed_count,
                weaken_score=weaken,
                trigger=str(pump.trigger or ""),
                cvd_divergence=reading.cvd_divergence,
                updated_at=now_ms,
                turnover_24h_usdt=float(turnover) if turnover is not None else None,
            )
        )

    grouped: dict[str, list[PumpSignalCard]] = {
        COLUMN_GREEN: [],
        COLUMN_YELLOW: [],
        COLUMN_RED: [],
        COLUMN_PURPLE: [],
    }
    for card in cards:
        grouped[card.column].append(card)

    columns = []
    for col_id, title, hint, sort_key in (
        (
            COLUMN_GREEN,
            "Готовы к шорту",
            "Памп остановился, разворот, откат от пика ≤15%",
            lambda c: (c.passed_count, c.weaken_score, c.growth_pct),
        ),
        (
            COLUMN_YELLOW,
            "Затухание",
            "Нет новых пиков, ослабление пампа",
            lambda c: (c.passed_count, c.weaken_score, c.growth_pct),
        ),
        (
            COLUMN_RED,
            "Активный рост",
            "Памп идёт, затухания мало",
            lambda c: (c.passed_count, c.weaken_score, c.growth_pct),
        ),
        (
            COLUMN_PURPLE,
            "Памп прошёл",
            "Откат от пика 15–70% — дамп уже идёт; при ≥70% монета с доски снимается",
            lambda c: (c.drawdown_pct or 0, c.since_peak_min or 0),
        ),
    ):
        ordered = sorted(grouped[col_id], key=sort_key, reverse=True)
        columns.append(
            {
                "id": col_id,
                "title": title,
                "hint": hint,
                "signals": [c.to_data() for c in ordered],
            }
        )

    return {
        "type": "pump_signals_board",
        "timestamp": now_ms,
        "data": {"columns": columns},
    }
