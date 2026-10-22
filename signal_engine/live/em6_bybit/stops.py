"""EMA6 Bybit: лестница стопа (только ужесточение): 50% → +5% → max−10% → trail 5%."""

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


def em6_bybit_initial_trail_roe_pct() -> float:
    return config.em6_bybit_trail_initial_roe()


def em6_bybit_ladder_target_stop_roe(current_roe: float, max_roe: float) -> float | None:
    """Минимальный ROE стопа по лестнице (long: чем выше, тем жёстче). До +20% — None (широкий trail)."""
    if current_roe + 1e-6 < config.em6_bybit_trail_profit_arm_roe():
        return None
    floor = config.em6_bybit_trail_lock_roe()
    if current_roe + 1e-6 >= config.em6_bybit_trail_profit_arm_roe():
        floor = max(floor, config.em6_bybit_trail_lock_roe())
    if max(current_roe, max_roe) + 1e-6 >= config.EM6_BYBIT_LADDER_ROE_2:
        floor = max(floor, max_roe - config.EM6_BYBIT_LADDER_BELOW_MAX)
    if current_roe + 1e-6 >= config.EM6_BYBIT_LADDER_ROE_3:
        floor = max(floor, current_roe - config.EM6_BYBIT_LADDER_TRAIL_3)
    return floor


def em6_bybit_use_tight_trail(current_roe: float) -> bool:
    return current_roe + 1e-6 >= config.EM6_BYBIT_LADDER_ROE_3


def em6_bybit_active_trail_roe_pct(current_roe: float) -> float:
    """До лестницы: 50%. На 3-й ступени: 5% от цены."""
    if em6_bybit_use_tight_trail(current_roe):
        return config.EM6_BYBIT_LADDER_TRAIL_3
    return em6_bybit_initial_trail_roe_pct()


def em6_bybit_profit_lock_trail_roe_pct(current_roe: float) -> float:
    """Устар.: совместимость UI — хвост для lock +5% при первом arm."""
    arm = config.em6_bybit_trail_profit_arm_roe()
    lock = config.em6_bybit_trail_lock_roe()
    return max(arm - lock, current_roe - lock)


def stop_price_for_roe(
    side: str,
    entry: float,
    margin: float,
    qty: float,
    stop_roe: float,
) -> float:
    fee = qty * entry * config.PAPER_FEE_RATE_TAKER
    lev = config.em6_bybit_leverage()
    if side == "long":
        if margin > 0:
            return net_roe_stop_price_long(entry, margin, stop_roe, lev, fee, 0.0)
        return price_for_long_roe(entry, stop_roe, lev)
    if margin > 0:
        return net_roe_stop_price(entry, margin, stop_roe, lev, fee, 0.0)
    return price_for_roe(entry, stop_roe, lev)


def em6_bybit_trailing_stop_price(
    entry: float,
    best_price: float,
    *,
    side: str,
    margin: float,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
    current_roe: float | None = None,
    locked_stop_roe: float | None = None,
) -> float:
    lev = config.em6_bybit_leverage()
    if side == "long":
        peak = long_roe_pct(entry, best_price, lev)
    else:
        peak = roe_pct(entry, best_price, lev)
    roe_for_trail = current_roe if current_roe is not None else peak
    if locked_stop_roe is not None and locked_stop_roe > -900:
        target_roe = locked_stop_roe
    else:
        target = em6_bybit_ladder_target_stop_roe(roe_for_trail, peak)
        if target is None:
            trail_gap = em6_bybit_initial_trail_roe_pct()
            target_roe = roe_for_trail - trail_gap if roe_for_trail > 0 else -trail_gap
        else:
            target_roe = target
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
    lev = config.em6_bybit_leverage()
    roe = (
        abs(float(trail_roe_pct))
        if trail_roe_pct is not None
        else config.em6_bybit_trail_initial_roe()
    )
    return ref_price * (roe / 100.0) / lev


def trail_roe_pct_from_trailing_distance(ref_price: float, trail_distance: float) -> float:
    lev = config.em6_bybit_leverage()
    if ref_price <= 0 or trail_distance <= 0:
        return 0.0
    return trail_distance / ref_price * lev * 100.0
