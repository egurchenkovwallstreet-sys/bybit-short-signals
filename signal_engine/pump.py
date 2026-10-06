"""Шаг 1. Памп: рост цены + всплеск объёма 5×+ на одном из TF (5m…1D)."""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from signal_engine.indicators import rsi, sma


@dataclass(frozen=True)
class PumpReading:
    price_change_5m: float | None
    price_change_15m: float | None
    price_change_1h: float | None
    price_change_24h: float | None
    volume_ratio: float | None
    rsi: float | None
    matched: bool
    volume_spikes: dict[str, float] = field(default_factory=dict)


def price_change_pct(closes: list[float], minutes: int, bar_minutes: int = 1) -> float | None:
    """Рост цены в процентах за minutes минут. Последнее закрытие — текущая цена."""
    steps = minutes // bar_minutes
    if steps < 1 or len(closes) <= steps:
        return None
    past = closes[-1 - steps]
    current = closes[-1]
    if past <= 0:
        return None
    return (current - past) / past * 100.0


def volume_ratio(volumes: list[float], period: int) -> float | None:
    """Текущий объём к средней предыдущих period баров. Текущий бар в среднюю не входит."""
    if len(volumes) < period + 1:
        return None
    baseline = sma(volumes[-period - 1 : -1], period)
    if baseline is None or baseline <= 0:
        return None
    return volumes[-1] / baseline


def period_volume_ratio(volumes: list[float], window: int) -> float | None:
    """Сумма объёма за последнее окно / сумма за такое же окно сразу до него."""
    if window < 1 or len(volumes) < window * 2:
        return None
    recent = sum(volumes[-window:])
    prior = sum(volumes[-window * 2 : -window])
    if prior <= 0:
        return None
    return recent / prior


def volume_spike_map(
    volumes_1m: list[float],
    volumes_4h: list[float] | None = None,
    volumes_1d: list[float] | None = None,
) -> dict[str, float]:
    spikes: dict[str, float] = {}
    for minutes in config.PUMP_VOLUME_SPIKE_WINDOWS_1M:
        ratio = period_volume_ratio(volumes_1m, minutes)
        if ratio is not None:
            spikes[f"{minutes}m"] = round(ratio, 2)
    r4 = period_volume_ratio(volumes_4h or [], 1)
    if r4 is not None:
        spikes["4h"] = round(r4, 2)
    r1d = period_volume_ratio(volumes_1d or [], 1)
    if r1d is not None:
        spikes["1D"] = round(r1d, 2)
    return spikes


def volume_spike_ok(spikes: dict[str, float], min_ratio: float | None = None) -> bool:
    floor = config.PUMP_VOLUME_SPIKE_MIN if min_ratio is None else min_ratio
    return any(value >= floor for value in spikes.values())


def _daily_change_pct(daily_closes: list[float]) -> float | None:
    if len(daily_closes) < 2:
        return None
    past = daily_closes[-2]
    current = daily_closes[-1]
    if past <= 0:
        return None
    return (current - past) / past * 100.0


def detect_pump(
    closes: list[float],
    volumes: list[float],
    *,
    daily_closes: list[float] | None = None,
    volumes_4h: list[float] | None = None,
    volumes_1d: list[float] | None = None,
) -> PumpReading:
    change_5m = price_change_pct(closes, 5)
    change_15m = price_change_pct(closes, 15)
    change_1h = price_change_pct(closes, 60)
    change_24h = price_change_pct(closes, 24 * 60)
    daily_change = _daily_change_pct(daily_closes or [])
    if daily_change is not None:
        if change_24h is None or daily_change > change_24h:
            change_24h = daily_change

    spikes = volume_spike_map(volumes, volumes_4h, volumes_1d)
    max_spike = max(spikes.values()) if spikes else None
    ratio = max_spike if max_spike is not None else volume_ratio(volumes, config.PUMP_VOLUME_MA_PERIOD)
    rsi_value = rsi(closes, config.PUMP_RSI_PERIOD)

    strong = (
        (change_1h is not None and change_1h >= config.PUMP_PRICE_CHANGE_1H)
        or (change_24h is not None and change_24h >= config.PUMP_PRICE_CHANGE_24H)
    )
    spike_ok = volume_spike_ok(spikes)
    matched = bool(strong and spike_ok)

    return PumpReading(
        change_5m,
        change_15m,
        change_1h,
        change_24h,
        ratio,
        rsi_value,
        matched,
        spikes,
    )
