"""Обнаружение эпизода пампа для лаборатории (жёсткие пороги роста и объёма)."""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.indicators import sma
from signal_engine.paper.detect import merged_15m
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
    volume_ratio: float | None
    source: str


def min_growth_pct(pump_class: str) -> float:
    if pump_class == "medium":
        return config.PUMP_LAB_GROWTH_MIN_MEDIUM
    if pump_class == "long":
        return config.PUMP_LAB_GROWTH_MIN_LONG
    return config.PUMP_LAB_GROWTH_MIN_FAST


def min_volume_ratio(pump_class: str) -> float:
    if pump_class == "fast":
        return config.PUMP_LAB_VOLUME_MIN_FAST
    if pump_class == "medium":
        return config.PUMP_LAB_VOLUME_MIN_MEDIUM
    return config.PUMP_LAB_VOLUME_MIN_LONG


def _volume_spike_on_leg(state: SymbolState, valley_ts: int, peak_ts: int) -> float | None:
    bars = merged_15m(state)
    if not bars:
        return None
    leg = [b for b in bars if valley_ts <= b.timestamp <= peak_ts]
    if not leg:
        return None
    before = [b for b in bars if b.timestamp < valley_ts]
    if len(before) < 5:
        return None
    base_bars = before[-20:]
    vols = [b.volume for b in base_bars if b.volume > 0]
    if not vols:
        return None
    base = sma(vols, min(20, len(vols)))
    if base is None or base <= 0:
        return None
    peak_vol = max(b.volume for b in leg)
    return peak_vol / base


def _draft_from_bars(state: SymbolState, now_ms: int) -> EpisodeDraft | None:
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
    if valley.low <= 0 or valley.timestamp >= peak_bar.timestamp:
        return None
    growth = (peak / valley.low - 1.0) * 100.0
    duration = max(0, peak_bar.timestamp - valley.timestamp)
    pump_class = pump_class_from_duration(duration)
    if growth < min_growth_pct(pump_class):
        return None
    vol_ratio = _volume_spike_on_leg(state, valley.timestamp, peak_bar.timestamp)
    if vol_ratio is None or vol_ratio < min_volume_ratio(pump_class):
        return None
    price = state.last_price or bars[-1].close
    if drawdown_from_peak_pct(price, peak) > config.PUMP_LAB_MAX_DRAWDOWN_PCT:
        return None
    return EpisodeDraft(
        symbol=state.symbol,
        valley_price=valley.low,
        valley_ts=valley.timestamp,
        peak_price=peak,
        peak_ts=peak_bar.timestamp,
        growth_pct=growth,
        pump_class=pump_class,
        volume_ratio=vol_ratio,
        source="bars",
    )


def detect_episode(state: SymbolState, now_ms: int) -> EpisodeDraft | None:
    return _draft_from_bars(state, now_ms)
