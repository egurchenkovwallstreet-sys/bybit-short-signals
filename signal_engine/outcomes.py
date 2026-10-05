"""Исход шорта: цель, ликвидация или выход по времени.

P&L % = ((Цена входа − Текущая цена) / Цена входа) × 100 × 10
Множитель 10 — только отображение из ТЗ, не рекомендация размера позиции.
"""

from __future__ import annotations

import config


def short_pnl_pct(entry: float, price: float) -> float | None:
    if entry <= 0 or price <= 0:
        return None
    return ((entry - price) / entry) * 100.0 * config.PNL_LEVERAGE


def classify_outcome(
    entry: float,
    price: float | None,
    created_at: int,
    now_ms: int,
) -> str | None:
    """Сначала цена, потом 24 часа. В один тик цель и ликвидация вместе не срабатывают."""
    if price is not None and entry > 0:
        move = (price - entry) / entry * 100.0
        if move <= -config.TP_PCT:
            return "TP_HIT"
        if move >= config.LIQUIDATION_PCT:
            return "LIQUIDATED"
    if now_ms - created_at >= config.TIME_EXIT_HOURS * 3_600_000:
        return "TIME_EXIT"
    return None
