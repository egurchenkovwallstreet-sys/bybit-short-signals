"""OI, спад объёма, CVD, taker ratio, OBV и funding."""

from __future__ import annotations

import config
from signal_engine.indicators import obv_change, sma
from signal_engine.liquidations import minute_start


def oi_change_pct(
    points: list[tuple[int, float]],
    lookback_min: int | None = None,
) -> float | None:
    """Изменение OI в процентах: последнее значение против точки в начале окна."""
    if len(points) < 2:
        return None
    lookback = config.OI_LOOKBACK_MIN if lookback_min is None else lookback_min
    latest_ts, latest = points[-1]
    cutoff = latest_ts - lookback * 60_000
    reference = points[0][1]
    for timestamp, value in points:
        if timestamp <= cutoff:
            reference = value
        else:
            break
    if reference <= 0:
        return None
    return (latest - reference) / reference * 100.0


def oi_falling(points: list[tuple[int, float]]) -> bool:
    change = oi_change_pct(points)
    return change is not None and change <= -config.OI_DROP_PCT


def volume_faded(volumes: list[float]) -> bool:
    """Пик был аномальным, а последний закрытый бар уже не выше 20-периодной средней.

    Последний элемент списка считается формирующимся баром и в сравнение не входит.
    """
    period = config.PUMP_VOLUME_MA_PERIOD
    lookback = config.VOLUME_LOOKBACK_BARS
    if len(volumes) < period + 2:
        return False
    closed = volumes[:-1]
    baseline = sma(closed, period)
    if baseline is None or baseline <= 0:
        return False
    peak = max(closed[-lookback:])
    last_closed = closed[-1]
    return peak >= baseline * config.PUMP_VOLUME_MULTIPLIER and last_closed <= baseline


def _sum_window(buckets: dict[int, float], now_ms: int, minutes: int) -> float:
    current = minute_start(now_ms)
    start = current - (minutes - 1) * 60_000
    total = 0.0
    cursor = start
    while cursor <= current:
        total += float(buckets.get(cursor, 0.0))
        cursor += 60_000
    return total


def cvd_window_change(buckets: dict[int, float], now_ms: int) -> float:
    """Сумма дельт CVD за окно дивергенции. Покупки плюс, продажи минус."""
    return _sum_window(buckets, now_ms, config.DIVERGENCE_LOOKBACK_MIN)


def cvd_bearish(buckets: dict[int, float], price_change_15m: float | None, now_ms: int) -> bool:
    """Цена обновила хай, а кумулятивная дельта за то же окно упала."""
    if price_change_15m is None or price_change_15m <= 0:
        return False
    return cvd_window_change(buckets, now_ms) < 0


def taker_ratio(buy: dict[int, float], sell: dict[int, float], now_ms: int) -> float | None:
    """Объём агрессивных покупок / объём агрессивных продаж. Ниже 1 — продавцы."""
    bought = _sum_window(buy, now_ms, config.TAKER_WINDOW_MIN)
    sold = _sum_window(sell, now_ms, config.TAKER_WINDOW_MIN)
    if bought == 0 and sold == 0:
        return None
    if sold == 0:
        return float("inf")
    return bought / sold


def taker_sellers_control(ratio: float | None) -> bool:
    return ratio is not None and ratio < 1.0


def obv_bearish(closes: list[float], volumes: list[float], price_change_15m: float | None) -> bool:
    if price_change_15m is None or price_change_15m <= 0:
        return False
    change = obv_change(closes, volumes, config.DIVERGENCE_LOOKBACK_MIN)
    return change is not None and change < 0


def funding_extreme(rate: float | None) -> bool:
    return rate is not None and rate >= config.FUNDING_EXTREME_RATE
