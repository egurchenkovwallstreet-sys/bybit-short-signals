"""EMA6 Bybit: trailing-only лестница 50% → 15% @ +20% ROE → 10% @ +50% ROE."""

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


def em6_bybit_ladder_trail_gap_candidate(current_roe: float) -> float:
    """Желаемый зазор trailing (ROE) от текущей цены по порогам."""
    if current_roe + 1e-6 >= config.em6_bybit_trail_tight_arm_roe():
        return config.em6_bybit_trail_tight_dist_roe()
    if current_roe + 1e-6 >= config.em6_bybit_trail_profit_arm_roe():
        return config.em6_bybit_trail_mid_dist_roe()
    return em6_bybit_initial_trail_roe_pct()


def em6_bybit_active_trail_roe_pct(
    current_roe: float,
    locked_trail_gap_roe: float | None = None,
) -> float:
    """Фактический/целевой зазор с учётом храповика (только ужесточение)."""
    cand = em6_bybit_ladder_trail_gap_candidate(current_roe)
    if locked_trail_gap_roe is None or locked_trail_gap_roe <= 0 or locked_trail_gap_roe > 900:
        return cand
    return min(locked_trail_gap_roe, cand)


def normalize_locked_trail_gap(raw: float | None) -> float:
    """Колонка locked_stop_roe в БД хранит зазор trailing (10 / 15 / 50)."""
    initial = em6_bybit_initial_trail_roe_pct()
    if raw is None:
        return initial
    v = float(raw)
    for ok in (
        initial,
        config.em6_bybit_trail_mid_dist_roe(),
        config.em6_bybit_trail_tight_dist_roe(),
    ):
        if abs(v - ok) < 0.05:
            return ok
    if v <= 0 or v > 900:
        return initial
    return initial


def stop_price_for_trail_gap(
    side: str,
    entry: float,
    ref_price: float,
    margin: float,
    trail_gap_roe: float,
    *,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Ориентир SL: ref_price минус trail_gap в ROE (для журнала/UI)."""
    lev = config.em6_bybit_leverage()
    if side == "long":
        roe_at_ref = long_roe_pct(entry, ref_price, lev)
    else:
        roe_at_ref = roe_pct(entry, ref_price, lev)
    stop_roe = roe_at_ref - abs(trail_gap_roe)
    if margin > 0:
        fee = entry_fee
        if side == "long":
            return net_roe_stop_price_long(entry, margin, stop_roe, lev, fee, funding_paid)
        return net_roe_stop_price(entry, margin, stop_roe, lev, fee, funding_paid)
    if side == "long":
        return price_for_long_roe(entry, stop_roe, lev)
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
    locked_trail_gap_roe: float | None = None,
    ref_price: float | None = None,
) -> float:
    lev = config.em6_bybit_leverage()
    ref = ref_price if ref_price and ref_price > 0 else best_price
    if side == "long":
        roe_for_trail = current_roe if current_roe is not None else long_roe_pct(entry, ref, lev)
    else:
        roe_for_trail = current_roe if current_roe is not None else roe_pct(entry, ref, lev)
    gap = em6_bybit_active_trail_roe_pct(roe_for_trail, locked_trail_gap_roe)
    return stop_price_for_trail_gap(
        side,
        entry,
        ref,
        margin,
        gap,
        entry_fee=entry_fee,
        funding_paid=funding_paid,
    )


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
