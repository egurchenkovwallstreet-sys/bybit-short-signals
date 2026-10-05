"""Шаг 1. Памп: цена, объём и RSI должны совпасть одновременно."""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.indicators import rsi, sma


@dataclass(frozen=True)
class PumpReading:
    price_change_5m: float | None
    price_change_15m: float | None
    volume_ratio: float | None
    rsi: float | None
    matched: bool


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


def detect_pump(closes: list[float], volumes: list[float]) -> PumpReading:
    change_5m = price_change_pct(closes, 5)
    change_15m = price_change_pct(closes, 15)
    ratio = volume_ratio(volumes, config.PUMP_VOLUME_MA_PERIOD)
    rsi_value = rsi(closes, config.PUMP_RSI_PERIOD)
    price_ok = (
        (change_5m is not None and change_5m >= config.PUMP_PRICE_CHANGE_5M)
        or (change_15m is not None and change_15m >= config.PUMP_PRICE_CHANGE_15M)
    )
    volume_ok = ratio is not None and ratio >= config.PUMP_VOLUME_MULTIPLIER
    rsi_ok = (
        rsi_value is not None
        and config.PUMP_RSI_MIN <= rsi_value <= config.PUMP_RSI_MAX
    )
    return PumpReading(change_5m, change_15m, ratio, rsi_value, price_ok and volume_ok and rsi_ok)
