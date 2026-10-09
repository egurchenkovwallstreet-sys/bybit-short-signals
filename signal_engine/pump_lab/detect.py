"""Обнаружение эпизода пампа для лаборатории."""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.paper.detect import find_pump, merged_15m
from signal_engine.pump import detect_pump
from signal_engine.pump_lab.phases import drawdown_from_peak_pct, pump_class_from_duration
from signal_engine.state import SymbolState


@dataclass
class EpisodeDraft:
    symbol: str
    valley_price: float
    valley_ts: int
    peak_price: float
    peak_ts: int
    growth_pct: float
    pump_class: str
    source: str


def _growth_from_bars(state: SymbolState, now_ms: int) -> EpisodeDraft | None:
    bars = merged_15m(state)
    if len(bars) < 12:
        return None
    window_ms = config.PUMP_LAB_MAX_AGE_DAYS * 24 * 3_600_000
    recent = [b for b in bars if b.timestamp >= now_ms - window_ms]
    if len(recent) < 8:
        return None
    peak_bar = max(recent, key=lambda b: b.high)
    peak = peak_bar.high
    if peak <= 0:
        return None
    valley = min(recent, key=lambda b: b.low)
    if valley.low <= 0:
        return None
    growth = (peak / valley.low - 1.0) * 100.0
    if growth < config.PUMP_LAB_MIN_GROWTH_PCT:
        return None
    price = state.last_price or bars[-1].close
    if drawdown_from_peak_pct(price, peak) > config.PUMP_LAB_MAX_DRAWDOWN_PCT:
        return None
    duration = max(0, peak_bar.timestamp - valley.timestamp)
    return EpisodeDraft(
        symbol=state.symbol,
        valley_price=valley.low,
        valley_ts=valley.timestamp,
        peak_price=peak,
        peak_ts=peak_bar.timestamp,
        growth_pct=growth,
        pump_class=pump_class_from_duration(duration),
        source="bars",
    )


def detect_episode(state: SymbolState, now_ms: int) -> EpisodeDraft | None:
    """Памп для лаборатории: paper find_pump, движок detect_pump или рост от min."""
    info = find_pump(state, None, now_ms)
    if info is not None:
        duration = info.duration_ms
        return EpisodeDraft(
            symbol=state.symbol,
            valley_price=info.valley_price,
            valley_ts=info.valley_ts,
            peak_price=info.peak_price,
            peak_ts=info.peak_ts,
            growth_pct=info.growth_pct,
            pump_class=pump_class_from_duration(duration),
            source="paper",
        )
    daily = [b.close for b in state.bars_htf.get("D", [])]
    vol4 = [b.volume for b in state.bars_htf.get("240", [])]
    vol1d = [b.volume for b in state.bars_htf.get("D", [])]
    reading = detect_pump(
        state.closes_1m(),
        state.volumes_1m(),
        daily_closes=daily,
        volumes_4h=vol4,
        volumes_1d=vol1d,
    )
    if reading.matched and state.last_price:
        draft = _growth_from_bars(state, now_ms)
        if draft is not None:
            draft.source = "engine_pump"
            return draft
    return _growth_from_bars(state, now_ms)
