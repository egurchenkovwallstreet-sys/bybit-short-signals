"""Локальные максимумы/минимумы (pivot) для графика и фильтра входа."""

from __future__ import annotations

import config


def pivot_highs(bars: list[dict], wing: int | None = None) -> list[dict]:
    """High выше wing соседей слева и справа. Крайние wing баров не считаются."""
    n = wing if wing is not None else config.PIVOT_NEIGHBORS
    if n < 1 or len(bars) < n * 2 + 1:
        return []
    out: list[dict] = []
    for i in range(n, len(bars) - n):
        high = float(bars[i]["h"])
        left = [float(bars[j]["h"]) for j in range(i - n, i)]
        right = [float(bars[j]["h"]) for j in range(i + 1, i + n + 1)]
        if high > max(left) and high > max(right):
            out.append(
                {
                    "time": int(float(bars[i]["t"]) // 1000),
                    "price": high,
                    "kind": "high",
                }
            )
    return out


def pivot_lows(bars: list[dict], wing: int | None = None) -> list[dict]:
    n = wing if wing is not None else config.PIVOT_NEIGHBORS
    if n < 1 or len(bars) < n * 2 + 1:
        return []
    out: list[dict] = []
    for i in range(n, len(bars) - n):
        low = float(bars[i]["l"])
        left = [float(bars[j]["l"]) for j in range(i - n, i)]
        right = [float(bars[j]["l"]) for j in range(i + 1, i + n + 1)]
        if low < min(left) and low < min(right):
            out.append(
                {
                    "time": int(float(bars[i]["t"]) // 1000),
                    "price": low,
                    "kind": "low",
                }
            )
    return out


def latest_pivot_high(bars: list[dict], wing: int | None = None) -> dict | None:
    highs = pivot_highs(bars, wing)
    return highs[-1] if highs else None


def price_near_pivot_high(
    bars: list[dict],
    price: float | None,
    *,
    wing: int | None = None,
    tolerance_pct: float | None = None,
    lookback: int = 3,
) -> bool:
    """Цена у одного из последних lookback подтверждённых максимумов."""
    if price is None or price <= 0 or not bars:
        return False
    tol = (
        tolerance_pct
        if tolerance_pct is not None
        else config.BTC_TEST_LONG_NEAR_SWING_HIGH_PCT
    )
    highs = pivot_highs(bars, wing)[-lookback:]
    for pivot in highs:
        level = float(pivot["price"])
        if level <= 0:
            continue
        if abs(price - level) / level * 100.0 <= tol:
            return True
    return False


def swings_for_chart(bars: list[dict], wing: int | None = None, limit: int = 24) -> dict:
    highs = pivot_highs(bars, wing)[-limit:]
    lows = pivot_lows(bars, wing)[-limit:]
    return {"highs": highs, "lows": lows}
