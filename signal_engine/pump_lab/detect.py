"""Обнаружение эпизода пампа: окно от «сейчас» назад по классу, дно → пик, объём."""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.pump_lab.bars import merged_15m
from signal_engine.pump_lab.phases import drawdown_from_peak_pct
from signal_engine.state import Bar, SymbolState

HOUR_MS = 3_600_000


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


def window_ms(pump_class: str) -> int:
    if pump_class == "medium":
        return config.PUMP_LAB_WINDOW_DAYS_MEDIUM * 24 * HOUR_MS
    if pump_class == "long":
        return config.PUMP_LAB_MAX_AGE_DAYS * 24 * HOUR_MS
    return config.PUMP_LAB_WINDOW_HOURS_FAST * HOUR_MS


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


def _avg_volume(bars: list[Bar]) -> float | None:
    vols = [b.volume for b in bars if b.volume > 0]
    if not vols:
        return None
    return sum(vols) / len(vols)


def _draft_for_class(state: SymbolState, now_ms: int, pump_class: str) -> EpisodeDraft | None:
    bars = merged_15m(state)
    if len(bars) < 8:
        return None
    win = window_ms(pump_class)
    recent = [b for b in bars if b.timestamp >= now_ms - win and b.timestamp <= now_ms]
    if len(recent) < 4:
        return None
    valley_bar = min(recent, key=lambda b: b.low)
    if valley_bar.low <= 0:
        return None
    after = [b for b in recent if b.timestamp >= valley_bar.timestamp]
    if len(after) < 2:
        return None
    peak_bar = max(after, key=lambda b: b.high)
    peak = peak_bar.high
    if peak <= 0 or peak_bar.timestamp <= valley_bar.timestamp:
        return None
    growth = (peak / valley_bar.low - 1.0) * 100.0
    if growth < min_growth_pct(pump_class):
        return None
    base = _avg_volume(recent)
    if base is None or base <= 0:
        return None
    leg = [b for b in after if b.timestamp <= peak_bar.timestamp]
    peak_vol = max((b.volume for b in leg), default=0.0)
    if peak_vol <= 0:
        return None
    vol_ratio = peak_vol / base
    if vol_ratio < min_volume_ratio(pump_class):
        return None
    price = state.last_price or bars[-1].close
    if drawdown_from_peak_pct(price, peak) > config.PUMP_LAB_MAX_DRAWDOWN_PCT:
        return None
    return EpisodeDraft(
        symbol=state.symbol,
        valley_price=valley_bar.low,
        valley_ts=valley_bar.timestamp,
        peak_price=peak,
        peak_ts=peak_bar.timestamp,
        growth_pct=growth,
        pump_class=pump_class,
        volume_ratio=vol_ratio,
        source="bars",
    )


def detect_episodes(state: SymbolState, now_ms: int) -> list[EpisodeDraft]:
    out: list[EpisodeDraft] = []
    for pump_class in ("fast", "medium", "long"):
        draft = _draft_for_class(state, now_ms, pump_class)
        if draft is not None:
            out.append(draft)
    return out


def detect_episode(state: SymbolState, now_ms: int) -> EpisodeDraft | None:
    """Один «лучший» эпизод (макс. рост) — для обратной совместимости."""
    drafts = detect_episodes(state, now_ms)
    if not drafts:
        return None
    return max(drafts, key=lambda d: d.growth_pct)
