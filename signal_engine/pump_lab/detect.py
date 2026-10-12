"""Обнаружение эпизода пампа — фасад над signal_engine.pump_unified."""

from __future__ import annotations

from signal_engine.pump_unified import (
    EpisodeDraft,
    detect_unified_episode as detect_episode,
    detect_unified_episodes as detect_episodes,
    max_drawdown_pct,
    meets_unified_turnover,
    min_growth_pct,
    min_volume_ratio,
    volume_ratio_min_to_peak,
    window_ms,
)

__all__ = [
    "EpisodeDraft",
    "detect_episode",
    "detect_episodes",
    "max_drawdown_pct",
    "meets_unified_turnover",
    "min_growth_pct",
    "min_volume_ratio",
    "volume_ratio_min_to_peak",
    "window_ms",
]
