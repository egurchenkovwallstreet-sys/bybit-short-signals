"""Свупы старших ТФ и проколы круглых уровней.

Сила уровня из ТЗ:
(Развороты × 3) + (Свупы × 2) + (Касания × 1) − (Пробои × 5).
Свуп: фитиль проколол уровень, закрытие вернулось обратно.
Мега-уровень: одна и та же цена есть и на 4H, и на 1D.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import config


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Level:
    price: float
    touches: int
    reversals: int
    sweeps: int
    breaks: int
    score: float
    kind: str
    last_event: str


def level_score(reversals: int, sweeps: int, touches: int, breaks: int) -> float:
    return (
        reversals * config.LEVEL_SCORE_REVERSAL
        + sweeps * config.LEVEL_SCORE_SWEEP
        + touches * config.LEVEL_SCORE_TOUCH
        - breaks * config.LEVEL_SCORE_BREAK
    )


def classify_level(score: float, last_event: str) -> str:
    """Сильный / средний / слабый / сломанный."""
    if last_event == "break" or score <= 0:
        return "broken"
    if score >= config.LEVEL_STRONG_MIN:
        return "strong"
    if score >= config.LEVEL_MEDIUM_MIN:
        return "medium"
    return "weak"


def quality_points(kind: str) -> int:
    return {"strong": 3, "medium": 2, "weak": 1}.get(kind, 0)


def _tolerance(price: float) -> float:
    return abs(price) * config.LEVEL_TOUCH_PCT / 100.0


def find_pivot_highs(candles: list[Candle], neighbors: int | None = None) -> list[float]:
    """High свечи выше N соседей слева и справа. Крайние N свечей ещё не подтверждены."""
    wing = config.PIVOT_NEIGHBORS if neighbors is None else neighbors
    if wing < 1 or len(candles) < wing * 2 + 1:
        return []
    pivots: list[float] = []
    for index in range(wing, len(candles) - wing):
        high = candles[index].high
        left = [candles[pos].high for pos in range(index - wing, index)]
        right = [candles[pos].high for pos in range(index + 1, index + wing + 1)]
        if high > max(left) and high > max(right):
            pivots.append(high)
    return pivots


def _unique_prices(prices: list[float]) -> list[float]:
    kept: list[float] = []
    for price in sorted(prices):
        if not kept:
            kept.append(price)
            continue
        mid = (kept[-1] + price) / 2.0
        if abs(price - kept[-1]) <= _tolerance(mid):
            continue
        kept.append(price)
    return kept


def _event(candle: Candle, price: float) -> str | None:
    tol = _tolerance(price)
    if candle.close > price + tol:
        return "break"
    if candle.high > price + tol and candle.close < price:
        return "sweep"
    if candle.high >= price - tol and candle.close <= price:
        return "touch"
    return None


def score_level(candles: list[Candle], price: float) -> Level:
    touches = reversals = sweeps = breaks = 0
    last_event = ""
    for index, candle in enumerate(candles):
        event = _event(candle, price)
        if event is None:
            continue
        last_event = event
        if event == "break":
            breaks += 1
            continue
        if event == "sweep":
            sweeps += 1
        else:
            touches += 1
        # Разворот — следующая свеча закрылась ниже уровня, а не сам факт свупа.
        if index + 1 < len(candles) and candles[index + 1].close < price - _tolerance(price):
            reversals += 1
    score = level_score(reversals, sweeps, touches, breaks)
    return Level(
        price=price,
        touches=touches,
        reversals=reversals,
        sweeps=sweeps,
        breaks=breaks,
        score=score,
        kind=classify_level(score, last_event),
        last_event=last_event,
    )


def analyze_levels(candles: list[Candle]) -> list[Level]:
    window = candles[-config.LEVEL_LOOKBACK_CANDLES :]
    prices = _unique_prices(find_pivot_highs(window))
    return [score_level(window, price) for price in prices]


def candle_swept_level(candle: Candle, level: Level) -> bool:
    if level.kind == "broken":
        return False
    return _event(candle, level.price) == "sweep"


def last_closed(candles: list[Candle], now_ms: int, interval_ms: int) -> list[Candle]:
    """Формирующаяся свеча в детект свупа не входит: фитиль ещё может не закрыться."""
    if not candles:
        return []
    if interval_ms > 0 and now_ms - candles[-1].timestamp < interval_ms:
        return candles[:-1]
    return candles


def sweep_on_timeframe(
    candles: list[Candle],
    now_ms: int,
    interval_ms: int,
) -> tuple[bool, list[Level], Candle | None]:
    """Пивоты считаются без последней свечи: её фитиль выше уровня и иначе сломал бы пивот."""
    closed = last_closed(candles, now_ms, interval_ms)
    if len(closed) < 2:
        return False, analyze_levels(closed), None
    levels = analyze_levels(closed[:-1])
    candle = closed[-1]
    swept = any(candle_swept_level(candle, level) for level in levels)
    return swept, levels, candle


def levels_align(left: list[Level], right: list[Level]) -> bool:
    """Одна цена на двух ТФ в пределах допуска — мега-уровень."""
    for first in left:
        if first.kind == "broken":
            continue
        for second in right:
            if second.kind == "broken":
                continue
            mid = (first.price + second.price) / 2.0
            if mid <= 0:
                continue
            if abs(first.price - second.price) <= _tolerance(mid):
                return True
    return False


def best_quality(levels: list[Level], prefer_swept: bool, candle: Candle | None) -> int:
    chosen = levels
    if prefer_swept and candle is not None:
        swept = [level for level in levels if candle_swept_level(candle, level)]
        if swept:
            chosen = swept
    if not chosen:
        return 0
    return max(quality_points(level.kind) for level in chosen)


def round_step(price: float) -> float:
    """Шаг круглой цены на порядок меньше самой цены: 16500 → 1000, 0.025 → 0.001."""
    if price <= 0:
        raise ValueError("цена должна быть положительной")
    exponent = math.floor(math.log10(price)) - 1
    return 10.0 ** exponent


def nearest_round_levels(price: float) -> list[float]:
    step = round_step(price)
    base = math.floor(price / step) * step
    # float даёт хвосты вроде 0.30000000000000004 — округляем к шагу.
    digits = max(0, -exponent_digits(step))
    low = round(base, digits)
    high = round(base + step, digits)
    return [low, high]


def exponent_digits(step: float) -> int:
    return math.floor(math.log10(step))


def is_up_pierce(candle: Candle, level: float) -> bool:
    """Фитиль ушёл выше круглой цены, закрытие вернулось ниже."""
    return candle.high > level and candle.close < level


def round_level_confirmed(candles: list[Candle]) -> bool:
    """2+ прокола одного круглого уровня в окне, и последний бар тоже прокол."""
    window = candles[-config.ROUND_LEVEL_WINDOW_BARS :]
    if not window:
        return False
    last = window[-1]
    if last.high <= 0:
        return False
    for level in nearest_round_levels(last.high):
        if not is_up_pierce(last, level):
            continue
        pierces = sum(1 for candle in window if is_up_pierce(candle, level))
        if pierces >= config.ROUND_LEVEL_MIN_PIERCES:
            return True
    return False


INTERVAL_MS = {
    "60": 60 * 60 * 1000,
    "240": 4 * 60 * 60 * 1000,
    "D": 24 * 60 * 60 * 1000,
}

INTERVAL_LABEL = {
    "60": "1H",
    "240": "4H",
    "D": "1D",
}
