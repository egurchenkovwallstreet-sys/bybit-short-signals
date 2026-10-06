"""Поиск пампа по истории свечей (до 7 дней)."""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.state import Bar, SymbolState


@dataclass(frozen=True)
class HistoryPump:
    min_low: float
    peak_high: float
    peak_mult: float
    current_mult: float
    valley_ts: int
    interval: str


def _pick_bars(state: SymbolState) -> tuple[str, list[Bar]]:
    # 4H даёт ~33d при лимите 200 — лучше для пампа длиннее недели.
    for key in ("240", "60", "D"):
        bars = state.bars_htf.get(key) or []
        if len(bars) >= config.X2_RETRACE_MIN_BARS:
            return key, bars
    return "", []


def history_pump_metrics(state: SymbolState, now_ms: int) -> HistoryPump | None:
    """max(high)/min(low) за LOOKBACK_DAYS — ловит памп даже после отката."""
    interval, bars = _pick_bars(state)
    if not bars:
        return None
    window_ms = config.X2_RETRACE_LOOKBACK_DAYS * 24 * 3600 * 1000
    window = [b for b in bars if b.timestamp >= now_ms - window_ms]
    if len(window) < config.X2_RETRACE_MIN_BARS:
        window = bars[-max(config.X2_RETRACE_MIN_BARS, len(bars)) :]

    def _metrics(segment: list[Bar]) -> tuple[float, float, int] | None:
        if len(segment) < config.X2_RETRACE_MIN_BARS:
            return None
        min_low = min(b.low for b in segment)
        peak_high = max(b.high for b in segment)
        if min_low <= 0 or peak_high <= 0:
            return None
        mult = peak_high / min_low
        if mult < config.X2_RETRACE_MIN_MULTIPLIER:
            return None
        valley_ts = max(b.timestamp for b in segment if b.low == min_low)
        return min_low, peak_high, valley_ts

    parsed = _metrics(window)
    if parsed is None:
        parsed = _metrics(bars[-config.LEVEL_LOOKBACK_CANDLES :])
    if parsed is None:
        return None
    min_low, peak_high, valley_ts = parsed
    peak_mult = peak_high / min_low
    last = state.last_price or bars[-1].close
    current_mult = float(last) / min_low
    return HistoryPump(
        min_low=min_low,
        peak_high=peak_high,
        peak_mult=peak_mult,
        current_mult=current_mult,
        valley_ts=valley_ts,
        interval=interval,
    )
