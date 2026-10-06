"""Оценка волатильности по часовым свечам (для выбора актива в тесте стратегии)."""

from __future__ import annotations

from typing import Any


def volatility_pct_24h(candles: list[dict[str, Any]], bars: int = 24) -> float | None:
    """Диапазон high/low и |изменение| за окно, в % от последней цены."""
    if len(candles) < max(8, bars // 2):
        return None
    window = candles[-bars:]
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    for row in window:
        try:
            highs.append(float(row["high"]))
            lows.append(float(row["low"]))
            closes.append(float(row["close"]))
        except (KeyError, TypeError, ValueError):
            continue
    if len(closes) < max(8, bars // 2):
        return None
    last = closes[-1]
    if not last:
        return None
    first = closes[0]
    range_pct = (max(highs) - min(lows)) / last * 100.0
    change_pct = abs((last - first) / first * 100.0) if first else 0.0
    return round(max(range_pct, change_pct), 2)
