"""EMA6 Bybit: −50% ROE до +20%; один раз trailing с lock +5% ROE — дальше только биржа."""

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


def em6_bybit_active_trail_roe_pct(current_roe: float) -> float:
    """Дистанция trailing до arm (+20% ROE): только широкий 50%."""
    if current_roe + 1e-6 >= config.em6_bybit_trail_profit_arm_roe():
        return em6_bybit_profit_lock_trail_roe_pct(current_roe)
    return config.em6_bybit_trail_initial_roe()


def em6_bybit_profit_lock_trail_roe_pct(current_roe: float) -> float:
    """Один раз при ROE ≥ arm: хвост = ROE − lock (+5%), стоп на lock; дальше не меняем."""
    arm = config.em6_bybit_trail_profit_arm_roe()
    lock = config.em6_bybit_trail_lock_roe()
    gap = max(0.1, arm - lock)
    return max(gap, current_roe - lock)


def em6_bybit_trailing_stop_price(
    entry: float,
    best_price: float,
    *,
    side: str,
    margin: float,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
    current_roe: float | None = None,
) -> float:
    """Стоп для UI (по текущему ROE если передан, иначе по best)."""
    lev = config.em6_bybit_leverage()
    if side == "long":
        peak = long_roe_pct(entry, best_price, lev)
    else:
        peak = roe_pct(entry, best_price, lev)
    roe_for_trail = current_roe if current_roe is not None else peak
    trail_gap = em6_bybit_active_trail_roe_pct(roe_for_trail)
    floor_roe = -config.em6_bybit_trail_initial_roe()
    if roe_for_trail + 1e-6 >= config.em6_bybit_trail_profit_arm_roe():
        floor_roe = config.em6_bybit_trail_lock_roe()
    target_roe = roe_for_trail - trail_gap if roe_for_trail > 0 else floor_roe
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


def trail_roe_pct_from_trailing_distance(ref_price: float, trail_distance: float) -> float:
    """Фактический trail ROE% по trailingStop и mark (обратно к trailing_stop_distance_price)."""
    lev = config.em6_bybit_leverage()
    if ref_price <= 0 or trail_distance <= 0:
        return 0.0
    return trail_distance / ref_price * lev * 100.0
