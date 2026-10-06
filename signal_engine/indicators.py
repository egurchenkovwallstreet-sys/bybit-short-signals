"""RSI, средняя и OBV. Считаются по уже собранным минутным барам."""

from __future__ import annotations

import numpy as np


def ema(values: list[float], period: int) -> list[float | None]:
    """EMA по всей серии; в начале None, пока мало данных."""
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2 / (period + 1)
    seed = float(sum(values[:period]) / period)
    out[period - 1] = seed
    prev = seed
    for index in range(period, len(values)):
        prev = values[index] * k + prev * (1 - k)
        out[index] = prev
    return out


def sma(values: list[float], period: int) -> float | None:
    """Простая средняя последних period значений."""
    if period < 1 or len(values) < period:
        return None
    window = np.asarray(values[-period:], dtype=float)
    return float(window.mean())


def rsi(closes: list[float], period: int) -> float | None:
    """RSI Уайлдера. None, пока закрытий меньше, чем period + 1."""
    if period < 1 or len(closes) < period + 1:
        return None
    deltas = np.diff(np.asarray(closes, dtype=float))
    gains = np.clip(deltas, 0, None)
    losses = np.clip(-deltas, 0, None)
    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())
    for index in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + float(gains[index])) / period
        avg_loss = (avg_loss * (period - 1) + float(losses[index])) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def obv_change(closes: list[float], volumes: list[float], lookback: int) -> float | None:
    """Насколько изменился OBV за lookback шагов. Падение при росте цены — дивергенция."""
    if lookback < 1 or len(closes) < lookback + 1 or len(closes) != len(volumes):
        return None
    obv = 0.0
    series: list[float] = []
    for index in range(1, len(closes)):
        if closes[index] > closes[index - 1]:
            obv += volumes[index]
        elif closes[index] < closes[index - 1]:
            obv -= volumes[index]
        series.append(obv)
    if len(series) <= lookback:
        return None
    return series[-1] - series[-1 - lookback]
