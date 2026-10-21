"""Утилиты фаз пампа (без лаборатории / вкладки «Анализ пампа»)."""

from __future__ import annotations

import config

_HOUR_MS = 3_600_000


def pump_class_from_duration(duration_ms: int) -> str:
    fast_max = int(config.PUMP_UNIFIED_WINDOW_HOURS_FAST) * _HOUR_MS
    medium_max = int(config.PUMP_UNIFIED_MEDIUM_MAX_MS)
    if duration_ms <= fast_max:
        return "fast"
    if duration_ms <= medium_max:
        return "medium"
    return "long"


def drawdown_from_peak_pct(price: float, peak: float) -> float:
    if peak <= 0 or price <= 0:
        return 0.0
    return max(0.0, (1.0 - price / peak) * 100.0)
