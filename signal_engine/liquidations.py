"""Шаг 2. Ликвидации шортов (S = Sell) и затухание потока на 70%+ от пика."""

from __future__ import annotations

import config


def minute_start(timestamp_ms: int) -> int:
    return (timestamp_ms // 60_000) * 60_000


def is_short_liquidation(side: str | None) -> bool:
    """Sell — ликвидирован шорт. Buy — лонг, в этот фильтр не входит."""
    return side == config.LIQUIDATION_SIDE_SHORT


def window_notionals(
    buckets: dict[int, float],
    now_ms: int,
    minutes: int | None = None,
) -> list[float]:
    """Минутные нотионалы, включая нулевые минуты. Последний элемент — текущая минута."""
    length = minutes if minutes is not None else config.LIQUIDATION_WINDOW_MIN
    if length < 1:
        return []
    current = minute_start(now_ms)
    start = current - (length - 1) * 60_000
    values: list[float] = []
    cursor = start
    while cursor <= current:
        values.append(float(buckets.get(cursor, 0.0)))
        cursor += 60_000
    return values


def liquidations_faded(buckets: list[float], fade_ratio: float | None = None) -> bool:
    """True, если пик в окне был и текущая минута упала от него не меньше чем на fade_ratio."""
    if not buckets:
        return False
    ratio = config.LIQUIDATION_FADE_RATIO if fade_ratio is None else fade_ratio
    peak = max(buckets)
    if peak <= 0:
        return False
    return buckets[-1] <= peak * (1.0 - ratio)
