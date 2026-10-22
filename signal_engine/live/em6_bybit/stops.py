"""Выход EMA6 Bybit: только трейл −14% ROE от пика по сделке."""

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


def em6_bybit_trailing_stop_price(
    entry: float,
    best_price: float,
    *,
    side: str,
    margin: float,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Стоп = не хуже −14% ROE; при профите — пик ROE − 14 п.п."""
    lev = config.em6_bybit_leverage()
    trail_gap = abs(float(config.PAPER_EM6R_INITIAL_STOP_ROE))
    floor_roe = -trail_gap
    if side == "long":
        peak = long_roe_pct(entry, best_price, lev)
        target_roe = peak - trail_gap if peak > 0 else floor_roe
        target_roe = max(target_roe, floor_roe)
        if margin > 0:
            return net_roe_stop_price_long(
                entry, margin, target_roe, lev, entry_fee, funding_paid
            )
        return price_for_long_roe(entry, target_roe, lev)
    peak = roe_pct(entry, best_price, lev)
    target_roe = peak - trail_gap if peak > 0 else floor_roe
    target_roe = max(target_roe, floor_roe)
    if margin > 0:
        return net_roe_stop_price(entry, margin, target_roe, lev, entry_fee, funding_paid)
    return price_for_roe(entry, target_roe, lev)


def trailing_stop_distance_price(ref_price: float) -> float:
    """Дистанция trailingStop на Bybit ≈ |−14% ROE| при текущем плече."""
    lev = config.em6_bybit_leverage()
    roe = abs(float(config.PAPER_EM6R_INITIAL_STOP_ROE))
    return ref_price * (roe / 100.0) / lev
