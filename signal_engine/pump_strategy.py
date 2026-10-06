"""Вкладка «Поиск пампов»: длинный рост (пока только он), липкий список."""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.flow import oi_change_pct
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars
from signal_engine.watch_store import WatchRow, WatchStore

BOARD_ID = "pump_strategy"

_MS_DAY = 24 * 3600 * 1000


@dataclass(frozen=True)
class LongPumpMatch:
    kind: str  # long
    growth_pct: float
    valley_price: float
    peak_price: float
    valley_ts: int
    peak_ts: int
    interval: str
    window_days: int


def _meets_turnover(state: SymbolState) -> bool:
    turnover = state.turnover_24h_usdt
    if turnover is None:
        return False
    return turnover >= config.PUMP_STRATEGY_MIN_TURNOVER_24H_USDT


def _pick_bars(state: SymbolState) -> tuple[str, list[Bar]]:
    for key in ("D", "240", "60"):
        bars = state.bars_htf.get(key) or []
        if len(bars) >= 5:
            return key, bars
    return "", []


def detect_long_pump(state: SymbolState, now_ms: int) -> LongPumpMatch | None:
    """Рост от минимума до максимума за окно до LONG_DAYS дней, порог LONG_MIN_PCT."""
    if not _meets_turnover(state):
        return None
    interval, bars = _pick_bars(state)
    if not bars:
        return None
    window_ms = config.PUMP_STRATEGY_LONG_DAYS * _MS_DAY
    closed = closed_bars(bars, interval, now_ms)
    window = [b for b in closed if b.timestamp >= now_ms - window_ms]
    if len(window) < 3:
        window = closed[-min(len(closed), config.PUMP_STRATEGY_LONG_DAYS + 1) :]
    if len(window) < 3:
        return None

    valley_bar = min(window, key=lambda b: b.low)
    valley_price = float(valley_bar.low)
    if valley_price <= 0:
        return None
    after = [b for b in window if b.timestamp >= valley_bar.timestamp]
    if not after:
        return None
    peak_bar = max(after, key=lambda b: b.high)
    peak_price = float(peak_bar.high)
    if peak_price <= 0:
        return None
    growth_pct = (peak_price - valley_price) / valley_price * 100.0
    if growth_pct < config.PUMP_STRATEGY_LONG_MIN_PCT:
        return None
    return LongPumpMatch(
        kind="long",
        growth_pct=growth_pct,
        valley_price=valley_price,
        peak_price=peak_price,
        valley_ts=int(valley_bar.timestamp),
        peak_ts=int(peak_bar.timestamp),
        interval=interval,
        window_days=config.PUMP_STRATEGY_LONG_DAYS,
    )


def format_period_ru(valley_ts: int, peak_ts: int) -> str:
    """Человекочитаемая длительность от дна до пика."""
    if peak_ts < valley_ts:
        return "—"
    hours = max(1, int(round((peak_ts - valley_ts) / 3_600_000)))
    if hours < 48:
        return f"{hours} ч"
    days = max(1, int(round(hours / 24)))
    return f"{days} д"


def _oi_metrics(state: SymbolState) -> tuple[float | None, float | None, float | None]:
    points = state.oi_points()
    if not points:
        return None, None, None
    last_oi = float(points[-1][1])
    ch1 = oi_change_pct(points, lookback_min=60)
    ch4 = oi_change_pct(points, lookback_min=240)
    return ch1, ch4, last_oi


@dataclass
class PumpStrategyItem:
    symbol: str
    kind: str
    growth_pct: float
    period_label: str
    turnover_24h_usdt: float
    last_price: float
    oi_change_1h_pct: float | None
    oi_change_4h_pct: float | None
    oi_last: float | None
    valley_price: float
    peak_price: float
    updated_at: int

    def to_data(self) -> dict:
        kind_label = "Длинный рост" if self.kind == "long" else self.kind
        return {
            "symbol": self.symbol,
            "kind": self.kind,
            "kind_label": kind_label,
            "growth_pct": round(self.growth_pct, 1),
            "period_label": self.period_label,
            "turnover_24h_usdt": self.turnover_24h_usdt,
            "last_price": self.last_price,
            "oi_change_1h_pct": _round_opt(self.oi_change_1h_pct),
            "oi_change_4h_pct": _round_opt(self.oi_change_4h_pct),
            "oi_last": self.oi_last,
            "valley_price": self.valley_price,
            "peak_price": self.peak_price,
            "updated_at": self.updated_at,
        }


def _round_opt(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _item_from_state(symbol: str, state: SymbolState, match: LongPumpMatch, now_ms: int) -> PumpStrategyItem:
    price = state.last_price or match.peak_price
    ch1, ch4, oi_last = _oi_metrics(state)
    return PumpStrategyItem(
        symbol=symbol,
        kind=match.kind,
        growth_pct=match.growth_pct,
        period_label=format_period_ru(match.valley_ts, match.peak_ts),
        turnover_24h_usdt=float(state.turnover_24h_usdt or 0),
        last_price=float(price),
        oi_change_1h_pct=ch1,
        oi_change_4h_pct=ch4,
        oi_last=oi_last,
        valley_price=match.valley_price,
        peak_price=match.peak_price,
        updated_at=now_ms,
    )


def _item_from_meta(symbol: str, state: SymbolState, meta: dict, now_ms: int) -> PumpStrategyItem | None:
    if state.last_price is None or state.last_price <= 0:
        return None
    growth = float(meta.get("growth_pct") or 0)
    ch1, ch4, oi_last = _oi_metrics(state)
    return PumpStrategyItem(
        symbol=symbol,
        kind=str(meta.get("kind") or "long"),
        growth_pct=growth,
        period_label=str(meta.get("period_label") or "—"),
        turnover_24h_usdt=float(state.turnover_24h_usdt or 0),
        last_price=float(state.last_price),
        oi_change_1h_pct=ch1,
        oi_change_4h_pct=ch4,
        oi_last=oi_last,
        valley_price=float(meta.get("valley_price") or 0),
        peak_price=float(meta.get("peak_price") or 0),
        updated_at=now_ms,
    )


def _should_exit(state: SymbolState | None) -> bool:
    if state is None:
        return True
    return not _meets_turnover(state)


def build_pump_strategy_board(states: dict[str, SymbolState], now_ms: int, watches: WatchStore) -> dict:
    active = watches.active(BOARD_ID)

    for symbol, state in states.items():
        if symbol in active:
            continue
        prior = watches.get(BOARD_ID, symbol)
        if prior is not None and prior.dismissed:
            continue
        match = detect_long_pump(state, now_ms)
        if match is None:
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
                "kind": match.kind,
                "growth_pct": match.growth_pct,
                "period_label": format_period_ru(match.valley_ts, match.peak_ts),
                "valley_price": match.valley_price,
                "peak_price": match.peak_price,
            },
        )
        watches.upsert(watch)
        active[symbol] = watch

    items: list[PumpStrategyItem] = []
    for symbol, watch in list(active.items()):
        state = states.get(symbol)
        if _should_exit(state):
            watches.remove(BOARD_ID, symbol)
            continue
        assert state is not None
        match = detect_long_pump(state, now_ms)
        if match is not None:
            item = _item_from_state(symbol, state, match, now_ms)
            watch.meta = {
                "kind": match.kind,
                "growth_pct": match.growth_pct,
                "period_label": item.period_label,
                "valley_price": match.valley_price,
                "peak_price": match.peak_price,
            }
            watches.upsert(watch)
        else:
            item = _item_from_meta(symbol, state, watch.meta, now_ms)
            if item is None:
                watches.remove(BOARD_ID, symbol)
                continue
        items.append(item)

    ordered = sorted(items, key=lambda row: row.growth_pct, reverse=True)
    return {
        "type": "pump_strategy_board",
        "timestamp": now_ms,
        "data": {"signals": [row.to_data() for row in ordered]},
    }
