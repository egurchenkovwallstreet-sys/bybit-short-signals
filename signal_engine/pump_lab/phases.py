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


def post_peak_correction_trough(
    state: SymbolState,
    peak_ts: int,
    peak_price: float,
) -> tuple[float | None, int | None, float]:
    """Минимум цены после пика (дно коррекции) и откат пик→дно, %."""
    bars = [b for b in merged_15m(state) if b.timestamp >= peak_ts]
    if not bars:
        return None, None, 0.0
    trough_bar = min(bars, key=lambda b: b.low)
    trough = trough_bar.low
    if trough <= 0:
        return None, None, 0.0
    retrace = drawdown_from_peak_pct(trough, peak_price)
    return trough, trough_bar.timestamp, retrace


def _trough_confirmed(
    state: SymbolState,
    peak_ts: int,
    trough: float,
    trough_ts: int,
    now_ms: int,
) -> bool:
    """Дно не «на лету»: прошло время и/или отскок, и после дна нет нового минимума."""
    bars = [b for b in merged_15m(state) if b.timestamp >= peak_ts]
    if not bars:
        return False
    age_min = max(0, int((now_ms - trough_ts) / MIN_MS))
    if age_min < config.PUMP_LAB_TROUGH_CONFIRM_MIN:
        return False
    after = [b for b in bars if b.timestamp > trough_ts]
    if not after:
        return False
    if not all(b.low >= trough * 0.997 for b in after):
        return False
    price = state.last_price or bars[-1].close
    bounce = config.PUMP_LAB_TROUGH_BOUNCE_PCT
    if price > trough * (1.0 + bounce / 100.0):
        return True
    return len(after) >= 1


def is_pump_passed(
    state: SymbolState,
    pump_class: str,
    peak_price: float,
    peak_ts: int,
    now_ms: int,
) -> tuple[bool, dict]:
    """Памп прошёл: откат от пика до сформированного дна коррекции (ориентир 20–40%)."""
    price = state.last_price or peak_price
    dd_now = drawdown_from_peak_pct(price, peak_price)
    trough, trough_ts, trough_retrace = post_peak_correction_trough(state, peak_ts, peak_price)
    meta: dict = {
        "drawdown_pct": round(dd_now, 2),
        "trough_retrace_pct": round(trough_retrace, 2),
        "trough_price": trough,
        "trough_ts": trough_ts,
    }
    if trough is None or trough_ts is None:
        return False, meta
    min_dd = passed_drawdown_pct(pump_class)
    if trough_retrace < min_dd:
        return False, meta
    if not _trough_confirmed(state, peak_ts, trough, trough_ts, now_ms):
        return False, meta
    # Глубина дна: от min_dd до max_dd — типичная коррекция; глубже max_dd — тоже «прошёл».
    meta["pump_passed"] = True
    meta["minutes_since_high"] = minutes_since_high(state, now_ms, peak_ts, peak_price)
    return True, meta


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
    passed, passed_meta = is_pump_passed(state, pump_class, peak_price, peak_ts, now_ms)
    if passed:
        return "purple", {
            **passed_meta,
            "range_since_peak_pct": None,
            "green_signals": 0,
        }
    price = state.last_price or peak_price
    dd = drawdown_from_peak_pct(price, peak_price)
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
