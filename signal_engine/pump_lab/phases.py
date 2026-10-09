"""Фазы пампа: red, yellow, green, purple (памп прошёл — снимаем с доски)."""

from __future__ import annotations

import config
from signal_engine.paper.detect import merged_15m
from signal_engine.state import SymbolState

MIN_MS = 60_000
HOUR_MS = 3_600_000


def pump_class_from_duration(duration_ms: int) -> str:
    if duration_ms <= config.PUMP_LAB_FAST_MAX_MS:
        return "fast"
    if duration_ms <= config.PUMP_LAB_MEDIUM_MAX_MS:
        return "medium"
    return "long"


def _stall_minutes(pump_class: str) -> int:
    if pump_class == "fast":
        return config.PUMP_LAB_PHASE_STALL_MIN_FAST
    if pump_class == "medium":
        return config.PUMP_LAB_PHASE_STALL_MIN_MED
    return config.PUMP_LAB_PHASE_STALL_MIN_LONG


def _dd_yellow(pump_class: str) -> float:
    if pump_class == "fast":
        return config.PUMP_LAB_PHASE_DD_YELLOW_FAST
    if pump_class == "medium":
        return config.PUMP_LAB_PHASE_DD_YELLOW_MED
    return config.PUMP_LAB_PHASE_DD_YELLOW_LONG


def passed_drawdown_pct(pump_class: str) -> float:
    if pump_class == "medium":
        return config.PUMP_LAB_PASSED_DD_MEDIUM
    if pump_class == "long":
        return config.PUMP_LAB_PASSED_DD_LONG
    return config.PUMP_LAB_PASSED_DD_FAST


def _dd_green(pump_class: str) -> float:
    if pump_class == "fast":
        return config.PUMP_LAB_PHASE_DD_GREEN_FAST
    if pump_class == "medium":
        return config.PUMP_LAB_PHASE_DD_GREEN_MED
    return config.PUMP_LAB_PHASE_DD_GREEN_LONG


def drawdown_from_peak_pct(price: float, peak: float) -> float:
    if peak <= 0 or price <= 0:
        return 0.0
    return max(0.0, (1.0 - price / peak) * 100.0)


def minutes_since_high(state: SymbolState, now_ms: int, peak_ts: int, peak_price: float) -> int:
    bars = merged_15m(state)
    if not bars:
        return 0
    last_high_ts = peak_ts
    for bar in bars:
        if bar.timestamp > peak_ts and bar.high >= peak_price * 0.999:
            last_high_ts = bar.timestamp
    return max(0, int((now_ms - last_high_ts) / MIN_MS))


def _range_pct_since_peak(state: SymbolState, peak_ts: int) -> float | None:
    bars = [b for b in merged_15m(state) if b.timestamp >= peak_ts]
    if len(bars) < 2:
        return None
    hi = max(b.high for b in bars)
    lo = min(b.low for b in bars)
    if lo <= 0:
        return None
    return (hi - lo) / lo * 100.0


def _lower_low(state: SymbolState, peak_ts: int) -> bool:
    bars = [b for b in merged_15m(state) if b.timestamp >= peak_ts]
    if len(bars) < 3:
        return False
    lows = [b.low for b in bars]
    return lows[-1] < min(lows[:-1])


def _sells_dominate(state: SymbolState, now_ms: int) -> bool:
    windows = (5, 10, 15)
    hits = 0
    current = (now_ms // MIN_MS) * MIN_MS
    for minutes in windows:
        start = current - minutes * MIN_MS
        buy = sell = 0.0
        for ts, val in state.taker_buy.items():
            if start <= ts <= current:
                buy += val
        for ts, val in state.taker_sell.items():
            if start <= ts <= current:
                sell += val
        total = buy + sell
        if total > 0 and sell / total > 0.5:
            hits += 1
    return hits >= 2


def compute_phase(
    state: SymbolState,
    pump_class: str,
    peak_price: float,
    peak_ts: int,
    now_ms: int,
) -> tuple[str, dict]:
    price = state.last_price or peak_price
    dd = drawdown_from_peak_pct(price, peak_price)
    if dd >= passed_drawdown_pct(pump_class):
        return "purple", {
            "drawdown_pct": round(dd, 2),
            "minutes_since_high": minutes_since_high(state, now_ms, peak_ts, peak_price),
            "range_since_peak_pct": None,
            "green_signals": 0,
            "pump_passed": True,
        }
    stall_min = _stall_minutes(pump_class)
    since_high = minutes_since_high(state, now_ms, peak_ts, peak_price)
    rng = _range_pct_since_peak(state, peak_ts)

    green_hits = 0
    if dd >= _dd_green(pump_class):
        green_hits += 1
    if _lower_low(state, peak_ts):
        green_hits += 1
    if _sells_dominate(state, now_ms):
        green_hits += 1

    if green_hits >= 2:
        phase = "green"
    elif since_high >= stall_min and dd < _dd_yellow(pump_class):
        phase = "yellow"
    elif since_high >= stall_min and dd >= _dd_yellow(pump_class) and green_hits < 2:
        phase = "yellow"
    elif dd >= _dd_yellow(pump_class) and green_hits >= 1:
        phase = "green"
    else:
        phase = "red"

    meta = {
        "drawdown_pct": round(dd, 2),
        "minutes_since_high": since_high,
        "range_since_peak_pct": round(rng, 2) if rng is not None else None,
        "green_signals": green_hits,
    }
    return phase, meta
