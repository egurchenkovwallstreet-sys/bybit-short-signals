"""Адаптивный порог отрыва и pre-entry «остывание» для EMA6 Bybit."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import config


def stretch_bucket_lower(stretch_pct: float) -> float | None:
    """Нижняя граница корзины 0.5% (пол 4%)."""
    floor = config.EM6_BYBIT_ADAPT_FLOOR_PCT
    step = config.EM6_BYBIT_ADAPT_BUCKET_STEP_PCT
    if stretch_pct + 1e-9 < floor:
        return None
    idx = math.floor((stretch_pct - floor) / step + 1e-9)
    return round(floor + idx * step, 4)


def compute_adaptive_threshold(stretches: list[float]) -> tuple[float, dict[float, int]]:
    """Порог = нижняя граница самой высокой корзины с ≥3 монетами; >5 монет → +0.5%."""
    step = config.EM6_BYBIT_ADAPT_BUCKET_STEP_PCT
    floor = config.EM6_BYBIT_ADAPT_FLOOR_PCT
    min_coins = config.EM6_BYBIT_ADAPT_MIN_COINS
    counts: dict[float, int] = {}
    for s in stretches:
        lo = stretch_bucket_lower(s)
        if lo is None:
            continue
        counts[lo] = counts.get(lo, 0) + 1

    confirmed = [(lo, n) for lo, n in counts.items() if n >= min_coins]
    if not confirmed:
        return floor, counts

    lo, n = max(confirmed, key=lambda x: x[0])
    threshold = lo
    if n > config.EM6_BYBIT_ADAPT_RAISE_IF_COINS:
        threshold = lo + step
    return max(floor, round(threshold, 4)), counts


@dataclass
class AdaptiveStretchRegime:
    threshold_pct: float = field(
        default_factory=lambda: config.EM6_BYBIT_ADAPT_FLOOR_PCT
    )
    last_recalc_ms: int = -1
    last_candidate_ms: int = 0
    bucket_counts: dict[float, int] = field(default_factory=dict)
    active_bucket_lo: float | None = None

    def note_candidate(self, now_ms: int) -> None:
        self.last_candidate_ms = now_ms

    def update(self, now_ms: int, stretches: list[float]) -> None:
        recalc_ms = config.EM6_BYBIT_ADAPT_RECALC_MS
        idle_ms = config.EM6_BYBIT_ADAPT_IDLE_MS
        due_scheduled = now_ms - self.last_recalc_ms >= recalc_ms
        due_idle = (
            self.last_candidate_ms > 0
            and now_ms - self.last_candidate_ms >= idle_ms
        )
        first = self.last_recalc_ms < 0
        if not (first or due_scheduled or due_idle):
            return
        self.last_recalc_ms = now_ms
        new_thr, counts = compute_adaptive_threshold(stretches)
        self.bucket_counts = counts
        self.threshold_pct = new_thr
        confirmed = [
            lo for lo, n in counts.items() if n >= config.EM6_BYBIT_ADAPT_MIN_COINS
        ]
        self.active_bucket_lo = max(confirmed) if confirmed else None

    def to_view(self) -> dict:
        return {
            "threshold_pct": round(self.threshold_pct, 2),
            "floor_pct": config.EM6_BYBIT_ADAPT_FLOOR_PCT,
            "active_bucket_lo": self.active_bucket_lo,
            "bucket_counts": {f"{k:g}": v for k, v in sorted(self.bucket_counts.items())},
        }


@dataclass
class PreEntryWatch:
    last_peak_ms: int = -1
    peak_stretch: float = 0.0
    last_sample_ms: int = -1
    cooldown_until_ms: int = 0

    def reset(self) -> None:
        self.last_peak_ms = -1
        self.peak_stretch = 0.0
        self.last_sample_ms = -1

    def in_cooldown(self, now_ms: int) -> bool:
        return now_ms < self.cooldown_until_ms

    def start_cooldown(self, now_ms: int) -> None:
        self.cooldown_until_ms = now_ms + config.EM6_BYBIT_INITIAL_STOP_COOLDOWN_MS
        self.reset()

    def tick(self, now_ms: int, stretch_pct: float) -> bool:
        """True если можно входить (20 с без нового max отрыва)."""
        if self.in_cooldown(now_ms):
            return False
        interval = config.EM6_BYBIT_WATCH_SAMPLE_MS
        if self.last_sample_ms < 0 or now_ms - self.last_sample_ms >= interval:
            self.last_sample_ms = now_ms
            if stretch_pct > self.peak_stretch + 1e-6:
                self.peak_stretch = stretch_pct
                self.last_peak_ms = now_ms
                return False
        stable_ms = config.EM6_BYBIT_WATCH_STABLE_MS
        if self.last_peak_ms < 0:
            self.peak_stretch = stretch_pct
            self.last_peak_ms = now_ms
            return False
        return now_ms - self.last_peak_ms >= stable_ms

    def phase(self, now_ms: int) -> str:
        if self.in_cooldown(now_ms):
            return "cooldown_15s"
        stable_ms = config.EM6_BYBIT_WATCH_STABLE_MS
        if self.last_peak_ms < 0 or now_ms - self.last_peak_ms < stable_ms:
            return "waiting_stretch"
        return "ready"
