"""Вход EMA6 Bybit: претенденты, сетка 0.25% от EMA, подтверждение 1m."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import config


def band_lo(stretch_pct: float) -> float:
    """Нижняя граница полосы отрыва (пол 6%, шаг 0.25%)."""
    floor = config.EM6_BYBIT_STRETCH_FLOOR_PCT
    step = config.EM6_BYBIT_BAND_STEP_PCT
    if stretch_pct + 1e-9 < floor:
        return floor
    idx = math.floor((stretch_pct - floor) / step + 1e-9)
    return round(floor + idx * step, 4)


def stretch_at_price(price: float, ema: float) -> float:
    if ema <= 0 or price <= 0:
        return 0.0
    return abs(price - ema) / ema * 100.0


def grid_anchor_stretch(peak_stretch: float, current_stretch: float) -> float:
    """Верх сетки: max(пик, текущий отрыв), не ниже пола мониторинга."""
    floor = config.EM6_BYBIT_STRETCH_FLOOR_PCT
    return max(floor, peak_stretch, current_stretch)


def level_bands(anchor_stretch: float) -> list[tuple[float, float]]:
    """Полосы от пола отрыва до anchor+away (в т.ч. при отрыве 20%+)."""
    floor = config.EM6_BYBIT_STRETCH_FLOOR_PCT
    step = config.EM6_BYBIT_BAND_STEP_PCT
    away = config.EM6_BYBIT_AWAY_BANDS_PCT
    anchor = max(floor, anchor_stretch)
    hi = anchor + away
    lo = floor
    bands: list[tuple[float, float]] = []
    x = lo
    while x + 1e-9 <= hi:
        bands.append((round(x, 4), round(x + step, 4)))
        x += step
    return bands


def build_grid_levels(
    ema: float,
    side: str,
    peak_stretch: float,
    current_stretch: float,
) -> list[dict[str, float]]:
    """Ценовые уровни сетки для UI и открытой позиции."""
    if ema <= 0:
        return []
    anchor = grid_anchor_stretch(peak_stretch, current_stretch)
    out: list[dict[str, float]] = []
    for lo, hi in level_bands(anchor):
        if side == "long":
            p_lo = price_at_stretch(ema, side, hi)
            p_hi = price_at_stretch(ema, side, lo)
        else:
            p_lo = price_at_stretch(ema, side, lo)
            p_hi = price_at_stretch(ema, side, hi)
        out.append(
            {
                "stretch_lo": lo,
                "stretch_hi": hi,
                "price_lo": p_lo,
                "price_hi": p_hi,
            }
        )
    return out


@dataclass
class CandidateWatch:
    symbol: str
    side: str
    since_ms: int
    peak_stretch: float = 0.0
    peak_price: float = 0.0
    ema60: float = 0.0
    last_stretch: float = 0.0
    last_band_lo: float = 0.0
    last_tick_ms: int = 0
    last_peak_ms: int = 0
    away_max_band_lo: float = 0.0
    stall_band_lo: float | None = None
    stall_band_hi: float | None = None
    phase: str = "watch"
    armed_entry_band_lo: float | None = None
    last_1m_ts: int = 0
    cooldown_until_ms: int = 0

    def update_peak(self, now_ms: int, stretch: float, price: float, ema: float) -> None:
        self.last_peak_ms = now_ms
        self.ema60 = ema
        if stretch > self.peak_stretch + 1e-6:
            self.peak_stretch = stretch
            self.peak_price = price
            if self.phase in ("cross_toward_ema", "stalled"):
                self.stall_band_lo = None
                self.stall_band_hi = None
                self.armed_entry_band_lo = None
                self.phase = "watch"

    def tick(
        self,
        now_ms: int,
        stretch: float,
        price: float,
        ema: float,
        closed_1m: tuple[int, float] | None,
    ) -> bool:
        """True — сигнал на вход."""
        if now_ms < self.cooldown_until_ms:
            return False
        self.ema60 = ema
        band = band_lo(stretch)
        prev = self.last_stretch
        self.last_tick_ms = now_ms

        if stretch > self.peak_stretch + 1e-6:
            self.peak_stretch = stretch
            self.peak_price = price
        if stretch > prev + 1e-6:
            self.phase = "away"
            if band > self.away_max_band_lo:
                self.away_max_band_lo = band
            self.stall_band_lo = band
            self.stall_band_hi = band + config.EM6_BYBIT_BAND_STEP_PCT
            self.armed_entry_band_lo = None
        elif band == self.last_band_lo and stretch <= prev + 1e-6:
            if self.phase in ("away", "watch") and self.stall_band_lo is not None:
                self.phase = "stalled"
        elif band + 1e-9 < self.last_band_lo:
            prev_band = self.last_band_lo
            if self.away_max_band_lo + 1e-9 >= prev_band or self.peak_stretch + 1e-9 >= prev_band:
                self.armed_entry_band_lo = band
                self.phase = "cross_toward_ema"
                if self.armed_entry_band_lo + 1e-9 < config.EM6_BYBIT_STRETCH_FLOOR_PCT:
                    self.armed_entry_band_lo = config.EM6_BYBIT_STRETCH_FLOOR_PCT
        elif stretch + 1e-6 < prev and self.stall_band_lo is not None:
            cross_lo = self.stall_band_lo
            if stretch + 1e-9 < cross_lo and self.away_max_band_lo >= cross_lo - 1e-9:
                target = cross_lo - config.EM6_BYBIT_BAND_STEP_PCT
                if target + 1e-9 < config.EM6_BYBIT_STRETCH_FLOOR_PCT:
                    target = config.EM6_BYBIT_STRETCH_FLOOR_PCT
                self.armed_entry_band_lo = target
                self.phase = "cross_toward_ema"

        self.last_stretch = stretch
        prev_band_lo = self.last_band_lo
        self.last_band_lo = band

        if self.armed_entry_band_lo is None or closed_1m is None:
            return False
        bar_ts, close_px = closed_1m
        if bar_ts <= self.last_1m_ts:
            return False
        close_stretch = stretch_at_price(close_px, ema)
        close_band = band_lo(close_stretch)
        target = self.armed_entry_band_lo
        step = config.EM6_BYBIT_BAND_STEP_PCT
        floor = config.EM6_BYBIT_STRETCH_FLOOR_PCT
        self.last_1m_ts = bar_ts
        if target - 1e-9 <= close_band <= target + step + 1e-9:
            return True
        if (
            self.phase == "cross_toward_ema"
            and close_band + 1e-9 < target
            and close_band + 1e-9 >= floor
            and (self.peak_stretch + 1e-9 >= prev_band_lo or self.away_max_band_lo + 1e-9 >= prev_band_lo)
        ):
            self.armed_entry_band_lo = close_band
            return True
        return False

    def start_cooldown(self, now_ms: int) -> None:
        self.cooldown_until_ms = now_ms + config.EM6_BYBIT_INITIAL_STOP_COOLDOWN_MS
        self.phase = "cooldown"
        self.armed_entry_band_lo = None

    def to_view(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "stretch_pct": round(self.last_stretch, 3),
            "band_lo": self.last_band_lo,
            "band_hi": round(self.last_band_lo + config.EM6_BYBIT_BAND_STEP_PCT, 3),
            "peak_stretch": round(self.peak_stretch, 3),
            "phase": self.phase,
            "away_max_band": self.away_max_band_lo,
            "stall": [self.stall_band_lo, self.stall_band_hi],
            "armed_band_lo": self.armed_entry_band_lo,
            "since_ms": self.since_ms,
            "ema60": round(self.ema60, 8) if self.ema60 else 0.0,
            "levels": level_bands(grid_anchor_stretch(self.peak_stretch, self.last_stretch)),
        }


def pick_top_candidates(
    rows: list[tuple[str, str, float, float]],
    *,
    limit: int,
) -> list[tuple[str, str, float]]:
    """(symbol, side, stretch) top by stretch."""
    floor = config.EM6_BYBIT_STRETCH_FLOOR_PCT
    ok = [(s, side, st) for s, side, st, _ in rows if st + 1e-9 >= floor]
    ok.sort(key=lambda x: x[2], reverse=True)
    return ok[:limit]


def price_at_stretch(ema: float, side: str, stretch_pct: float) -> float:
    if ema <= 0:
        return 0.0
    if side == "long":
        return ema * (1.0 - stretch_pct / 100.0)
    return ema * (1.0 + stretch_pct / 100.0)


def stretch_column_label(stretch: float) -> str:
    lo = band_lo(stretch)
    hi = round(lo + config.EM6_BYBIT_BAND_STEP_PCT, 2)
    return f"{lo:g}–{hi:g}%"
