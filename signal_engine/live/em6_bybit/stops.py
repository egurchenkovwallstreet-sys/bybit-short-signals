"""Выход EMA6 Bybit: trail −10% ROE; после ROE ≥ +2% → trail −5% ROE от цены."""

from __future__ import annotations

import config
from signal_engine.paper.position import (
    long_roe_pct,
    net_roe_stop_price,
    net_roe_stop_price_long,
    price_for_long_roe,
    price_for_roe,
    roe_pct,
)


def em6_bybit_active_trail_roe_pct(peak_roe: float) -> float:
    """Активная дистанция trailingStop на бирже (п.п. ROE)."""
    if peak_roe + 1e-6 >= config.em6_bybit_trail_arm_roe():
        return config.em6_bybit_trail_tight_roe()
    return config.em6_bybit_trail_initial_roe()


def em6_bybit_trailing_stop_price(
    entry: float,
    best_price: float,
    *,
    side: str,
    margin: float,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Стоп для UI: пик ROE − trail; пол не хуже −initial ROE."""
    lev = config.em6_bybit_leverage()
    if side == "long":
        peak = long_roe_pct(entry, best_price, lev)
    else:
        peak = roe_pct(entry, best_price, lev)
    trail_gap = em6_bybit_active_trail_roe_pct(peak)
    floor_roe = -config.em6_bybit_trail_initial_roe()
    target_roe = peak - trail_gap if peak > 0 else floor_roe
    target_roe = max(target_roe, floor_roe)
    if side == "long":
        if margin > 0:
            return net_roe_stop_price_long(
                entry, margin, target_roe, lev, entry_fee, funding_paid
            )
        return price_for_long_roe(entry, target_roe, lev)
    if margin > 0:
        return net_roe_stop_price(entry, margin, target_roe, lev, entry_fee, funding_paid)
    return price_for_roe(entry, target_roe, lev)


def trailing_stop_distance_price(ref_price: float, trail_roe_pct: float | None = None) -> float:
    """Дистанция trailingStop на Bybit ≈ |trail ROE%| при текущем плече."""
    lev = config.em6_bybit_leverage()
    roe = (
        abs(float(trail_roe_pct))
        if trail_roe_pct is not None
        else config.em6_bybit_trail_initial_roe()
    )
    return ref_price * (roe / 100.0) / lev
