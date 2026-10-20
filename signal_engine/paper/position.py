"""Виртуальный изолированный шорт: ликвидация, трейлинг-стоп, комиссии, funding.

ROE — прибыль в % от маржи без комиссий: (вход − цена) / вход × плечо × 100.
t20: ≥3% → +0.5% net, ≥7% — не хуже +5%, дальше трейл «пик − 20 п.п.».
p10: +3% → +0.5% net, +10% → +2% net; бумажный трейл 10%→2% цены плюс лок пик − 10 с пика ≥ 10%.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config


def liquidation_price(entry: float, leverage: int | None = None, mmr: float | None = None) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    rate = config.PAPER_MAINT_MARGIN_RATE if mmr is None else mmr
    return entry * (1.0 + 1.0 / lev - rate)


def roe_pct(entry: float, price: float, leverage: int | None = None) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    if entry <= 0:
        return 0.0
    return (entry - price) / entry * lev * 100.0


def long_roe_pct(entry: float, price: float, leverage: int | None = None) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    if entry <= 0:
        return 0.0
    return (price - entry) / entry * lev * 100.0


def long_liquidation_price(entry: float, leverage: int | None = None, mmr: float | None = None) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    rate = config.PAPER_MAINT_MARGIN_RATE if mmr is None else mmr
    return entry * (1.0 - 1.0 / lev + rate)


def price_for_long_roe(entry: float, roe: float, leverage: int | None = None) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    return entry * (1.0 + roe / (100.0 * lev))


def net_breakeven_stop_price_long(
    entry: float,
    margin: float,
    leverage: int | None = None,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    if entry <= 0 or margin <= 0:
        return entry
    qty = margin * lev / entry
    fee = config.PAPER_FEE_RATE_TAKER
    return (entry * qty + entry_fee - funding_paid) / (qty * (1.0 - fee))


def net_roe_stop_price_long(
    entry: float,
    margin: float,
    roe_pct: float,
    leverage: int | None = None,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    if entry <= 0 or margin <= 0:
        return entry
    qty = margin * lev / entry
    fee = config.PAPER_FEE_RATE_TAKER
    target_pnl = margin * roe_pct / 100.0
    return (entry * qty + entry_fee - funding_paid + target_pnl) / (qty * (1.0 - fee))


def trail_stop_long(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    peak = long_roe_pct(entry, best_price, lev)
    if peak <= 0:
        return net_roe_stop_price_long(
            entry, margin, config.PAPER_LONG_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
        )
    if peak < config.PAPER_LONG_LOCK_ARM_ROE:
        if margin > 0:
            return net_breakeven_stop_price_long(entry, margin, lev, entry_fee, funding_paid)
        return price_for_long_roe(entry, 0.0, lev)
    lock_roe = max(config.PAPER_LONG_LOCK_MIN_ROE, peak - config.PAPER_LONG_TRAIL_GAP_ROE)
    return price_for_long_roe(entry, lock_roe, lev)


def trail_distance_pct(best_roe: float) -> float:
    start = config.PAPER_TRAIL_START_DIST_PCT
    floor = config.PAPER_TRAIL_MIN_DIST_PCT
    lo = config.PAPER_TRAIL_TIGHTEN_FROM_ROE
    hi = config.PAPER_TRAIL_TIGHTEN_TO_ROE
    if best_roe <= lo:
        return start
    if best_roe >= hi:
        return floor
    share = (best_roe - lo) / (hi - lo)
    return start - (start - floor) * share


def price_for_roe(entry: float, roe: float, leverage: int | None = None) -> float:
    """Цена шорта, при которой gross ROE равен roe."""
    lev = leverage or config.PAPER_LEVERAGE
    return entry * (1.0 - roe / (100.0 * lev))


def net_roe_stop_price(
    entry: float,
    margin: float,
    roe_pct: float,
    leverage: int | None = None,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Цена выхода шорта с заданным net ROE (% от маржи)."""
    lev = leverage or config.PAPER_LEVERAGE
    if entry <= 0 or margin <= 0:
        return entry
    qty = margin * lev / entry
    fee = config.PAPER_FEE_RATE_TAKER
    target_pnl = margin * roe_pct / 100.0
    return (entry * qty - entry_fee + funding_paid - target_pnl) / (qty * (1.0 + fee))


def net_breakeven_stop_price(
    entry: float,
    margin: float,
    leverage: int | None = None,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Цена выхода шорта, при которой net P&L (комиссии + funding) ≈ 0."""
    lev = leverage or config.PAPER_LEVERAGE
    if entry <= 0 or margin <= 0:
        return entry
    qty = margin * lev / entry
    fee = config.PAPER_FEE_RATE_TAKER
    return (entry * qty - entry_fee + funding_paid) / (qty * (1.0 + fee))


def css_trail_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Cursor SS: стоп −15% ROE, с пика ≥ +10% ROE — net-безубыток, дальше трейл 20 п.п."""
    lev = leverage or config.PAPER_LEVERAGE
    peak = roe_pct(entry, best_price, lev)
    initial = net_roe_stop_price(
        entry, margin, config.PAPER_CSS_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
    )
    if peak < config.PAPER_CSS_BE_ARM_ROE:
        return initial
    be = net_breakeven_stop_price(entry, margin, lev, entry_fee, funding_paid)
    lock_roe = peak - config.PAPER_CSS_TRAIL_GAP_ROE
    if lock_roe <= 0:
        return be
    return min(be, price_for_roe(entry, lock_roe, lev))


def css2_trail_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
    scaled_half: bool = False,
) -> float:
    """Курсор СС 2: стоп −60% ROE, с +50% ROE — вход, после половины — лок +50% ROE."""
    lev = leverage or config.PAPER_LEVERAGE
    peak = roe_pct(entry, best_price, lev)
    initial = net_roe_stop_price(
        entry, margin, config.PAPER_CSS2_STOP_ROE, lev, entry_fee, funding_paid
    )
    if scaled_half:
        locked = price_for_roe(entry, config.PAPER_CSS2_LOCK_ROE, lev)
        return min(initial, locked)
    if peak < config.PAPER_CSS2_BE_ARM_ROE:
        return initial
    return min(initial, net_breakeven_stop_price(entry, margin, lev, entry_fee, funding_paid))


def sc10_trail_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
    side: str = "short",
) -> float:
    """Скальп 10: стоп всегда на 10 п.п. ROE позади пика (с входа это −10% ROE)."""
    lev = leverage or config.PAPER_LEVERAGE
    gap = config.PAPER_SC10_TRAIL_GAP_ROE
    if side == "long":
        peak = long_roe_pct(entry, best_price, lev)
        return net_roe_stop_price_long(
            entry, margin, peak - gap, lev, entry_fee, funding_paid
        )
    peak = roe_pct(entry, best_price, lev)
    return net_roe_stop_price(entry, margin, peak - gap, lev, entry_fee, funding_paid)


def e5s_trail_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """e5s: −20% ROE, с +5% — +1% net, с +10% — стоп +5% и трейл пик − 20 п.п., не ниже +5%."""
    lev = leverage or config.PAPER_LEVERAGE
    peak = roe_pct(entry, best_price, lev)
    initial = net_roe_stop_price(
        entry, margin, config.PAPER_E5S_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
    )
    if peak < config.PAPER_E5S_PLUS5_ARM_ROE:
        return initial
    plus = net_roe_stop_price(
        entry, margin, config.PAPER_E5S_PLUS5_LOCK_NET_ROE, lev, entry_fee, funding_paid
    )
    if peak < config.PAPER_E5S_BE_ARM_ROE:
        return min(initial, plus)
    lock_roe = max(config.PAPER_E5S_PLUS10_LOCK_ROE, peak - config.PAPER_E5S_TRAIL_GAP_ROE)
    return min(initial, plus, price_for_roe(entry, lock_roe, lev))


def e5p_trail_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """EMA 5+: −20% ROE, с +5% — +1% net и трейл пик − 3 п.п. ROE, не ниже +1% net."""
    lev = leverage or config.PAPER_LEVERAGE
    peak = roe_pct(entry, best_price, lev)
    initial = net_roe_stop_price(
        entry, margin, config.PAPER_E5S_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
    )
    if peak < config.PAPER_E5S_PLUS5_ARM_ROE:
        return initial
    plus = net_roe_stop_price(
        entry, margin, config.PAPER_E5S_PLUS5_LOCK_NET_ROE, lev, entry_fee, funding_paid
    )
    stop = min(initial, plus)
    lock_roe = peak - config.PAPER_E5P_TRAIL_GAP_ROE
    if lock_roe > 0:
        stop = min(stop, price_for_roe(entry, lock_roe, lev))
    return stop


def mln_trail_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Молния: −10% ROE, +2.5%→+2%, +6%→+4%, +7%→+5%, дальше трейл пик − 20 п.п."""
    lev = leverage or config.PAPER_LEVERAGE
    peak = roe_pct(entry, best_price, lev)
    initial = net_roe_stop_price(
        entry, margin, config.PAPER_MLN_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
    )
    if peak < config.PAPER_MLN_LOCK2_ARM_ROE - 1e-6:
        return initial
    stop = min(initial, price_for_roe(entry, config.PAPER_MLN_LOCK2_ROE, lev))
    if peak < config.PAPER_MLN_LOCK4_ARM_ROE - 1e-6:
        return stop
    stop = min(stop, price_for_roe(entry, config.PAPER_MLN_LOCK4_ROE, lev))
    if peak < config.PAPER_MLN_LOCK5_ARM_ROE - 1e-6:
        return stop
    trail = max(config.PAPER_MLN_LOCK5_ROE, peak - config.PAPER_MLN_TRAIL_GAP_ROE)
    return min(stop, price_for_roe(entry, trail, lev))


def _net_lock_price(
    entry: float,
    margin: float,
    net_roe: float,
    leverage: int,
    entry_fee: float,
    funding_paid: float,
) -> float:
    if margin > 0:
        return net_roe_stop_price(entry, margin, net_roe, leverage, entry_fee, funding_paid)
    return price_for_roe(entry, net_roe, leverage)


def _profit_lock_prices(
    entry: float,
    peak: float,
    leverage: int,
    margin: float,
    entry_fee: float,
    funding_paid: float,
    *,
    include_plus10: bool,
) -> list[float]:
    prices: list[float] = []
    if peak >= config.PAPER_BE_ARM_ROE:
        prices.append(
            _net_lock_price(entry, margin, config.PAPER_BE_LOCK_NET_ROE, leverage, entry_fee, funding_paid)
        )
    if include_plus10 and peak >= config.PAPER_PLUS10_ARM_ROE:
        prices.append(
            _net_lock_price(
                entry, margin, config.PAPER_PLUS10_LOCK_NET_ROE, leverage, entry_fee, funding_paid
            )
        )
    return prices


def bab_pivot_stop_price(
    side: str,
    pivot_high: float,
    pivot_low: float,
    leverage: int | None = None,
) -> float:
    """Стоп: шорт — на 5% ROE выше high pivot-свечи; лонг — на 5% ROE ниже low."""
    lev = leverage or config.PAPER_LEVERAGE
    roe = -abs(config.PAPER_PYL_STOP_ROE)
    if side == "long":
        return price_for_long_roe(pivot_low, roe, lev)
    return price_for_roe(pivot_high, roe, lev)


def _trail333_stop_prices_short(
    entry: float,
    peak: float,
    lev: int,
    *,
    margin: float,
    entry_fee: float,
    funding_paid: float,
) -> list[float]:
    prices: list[float] = [
        _net_lock_price(
            entry,
            margin,
            config.PAPER_333_TRAIL_LOCK_NET_ROE,
            lev,
            entry_fee,
            funding_paid,
        ),
        price_for_roe(entry, peak - config.PAPER_333_TRAIL_GAP_ROE, lev),
    ]
    if peak >= config.PAPER_333_LOCK5_ARM_ROE:
        prices.append(price_for_roe(entry, config.PAPER_333_LOCK5_ROE, lev))
    if peak >= config.PAPER_333_LOCK10_ARM_ROE:
        prices.append(price_for_roe(entry, config.PAPER_333_LOCK10_ROE, lev))
    return prices


def _trail333_stop_prices_long(
    entry: float,
    peak: float,
    lev: int,
    *,
    margin: float,
    entry_fee: float,
    funding_paid: float,
) -> list[float]:
    prices: list[float] = [
        net_roe_stop_price_long(
            entry,
            margin,
            config.PAPER_333_TRAIL_LOCK_NET_ROE,
            lev,
            entry_fee,
            funding_paid,
        ),
        price_for_long_roe(entry, peak - config.PAPER_333_TRAIL_GAP_ROE, lev),
    ]
    if peak >= config.PAPER_333_LOCK5_ARM_ROE:
        prices.append(price_for_long_roe(entry, config.PAPER_333_LOCK5_ROE, lev))
    if peak >= config.PAPER_333_LOCK10_ARM_ROE:
        prices.append(price_for_long_roe(entry, config.PAPER_333_LOCK10_ROE, lev))
    return prices


def trail333_stop_short(
    entry: float,
    best_price: float,
    bab_stop: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """333 шорт: pivot до +5% ROE; +5% +0.5% net; +10%→+5%; +14%→+10%; трейл пик−15 п.п."""
    lev = leverage or config.PAPER_LEVERAGE
    peak = roe_pct(entry, best_price, lev)
    if peak < config.PAPER_333_TRAIL_ARM_ROE:
        return bab_stop
    trail = min(
        _trail333_stop_prices_short(
            entry, peak, lev, margin=margin, entry_fee=entry_fee, funding_paid=funding_paid
        )
    )
    return min(trail, bab_stop)


def trail333_stop_long(
    entry: float,
    best_price: float,
    bab_stop: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """333 лонг: pivot до +5% ROE; +5% +0.5% net; +10%→+5%; +14%→+10%; трейл пик−15 п.п."""
    lev = leverage or config.PAPER_LEVERAGE
    peak = long_roe_pct(entry, best_price, lev)
    if peak < config.PAPER_333_TRAIL_ARM_ROE:
        return bab_stop
    trail = max(
        _trail333_stop_prices_long(
            entry, peak, lev, margin=margin, entry_fee=entry_fee, funding_paid=funding_paid
        )
    )
    return max(trail, bab_stop)


def pyl_trail_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """БАБЛОСОС: −10% → +3% net +0.5% → +7% +5% ROE → +10% трейл пик−5 п.п."""
    lev = leverage or config.PAPER_LEVERAGE
    peak = roe_pct(entry, best_price, lev)
    liq = liquidation_price(entry, lev)
    if peak < config.PAPER_BE_ARM_ROE:
        initial = net_roe_stop_price(
            entry, margin, config.PAPER_PYL_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
        )
        return min(initial, liq)
    stops: list[float] = []
    if peak >= config.PAPER_BE_ARM_ROE:
        stops.append(
            net_roe_stop_price(
                entry, margin, config.PAPER_BE_LOCK_NET_ROE, lev, entry_fee, funding_paid
            )
        )
    if peak >= config.PAPER_LOCK_ARM_ROE:
        stops.append(price_for_roe(entry, config.PAPER_LOCK_MIN_ROE, lev))
    if peak >= config.PAPER_PYL_TRAIL_ARM_ROE:
        trail_roe = peak - config.PAPER_PYL_TRAIL_GAP_ROE
        if peak >= config.PAPER_LOCK_ARM_ROE:
            trail_roe = max(config.PAPER_LOCK_MIN_ROE, trail_roe)
        stops.append(price_for_roe(entry, trail_roe, lev))
    if not stops:
        return min(
            net_roe_stop_price(
                entry, margin, config.PAPER_PYL_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
            ),
            liq,
        )
    return min(min(stops), liq)


def vps_trail_stop_short(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Пылесос 5/15: сразу −15% net, с +3% пол +0.5% net, с +7% не хуже +5% и трейл пик − 20 п.п."""
    lev = leverage or config.PAPER_LEVERAGE
    peak = roe_pct(entry, best_price, lev)
    initial = net_roe_stop_price(
        entry, margin, config.PAPER_VPS_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
    )
    if peak < config.PAPER_BE_ARM_ROE:
        return initial
    lock_net = net_roe_stop_price(
        entry, margin, config.PAPER_BE_LOCK_NET_ROE, lev, entry_fee, funding_paid
    )
    if peak < config.PAPER_LOCK_ARM_ROE:
        return lock_net
    lock_roe = max(config.PAPER_LOCK_MIN_ROE, peak - config.PAPER_TRAIL_GAP_ROE)
    return min(price_for_roe(entry, lock_roe, lev), lock_net)


def vps_trail_stop_long(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Лонг Пылесоса: сразу −15% net, дальше те же ступени, что у шорта."""
    lev = leverage or config.PAPER_LEVERAGE
    peak = long_roe_pct(entry, best_price, lev)
    initial = net_roe_stop_price_long(
        entry, margin, config.PAPER_VPS_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
    )
    if peak < config.PAPER_BE_ARM_ROE:
        return initial
    lock_net = net_roe_stop_price_long(
        entry, margin, config.PAPER_BE_LOCK_NET_ROE, lev, entry_fee, funding_paid
    )
    if peak < config.PAPER_LOCK_ARM_ROE:
        return lock_net
    lock_roe = max(config.PAPER_LOCK_MIN_ROE, peak - config.PAPER_TRAIL_GAP_ROE)
    return max(price_for_long_roe(entry, lock_roe, lev), lock_net)


def trail_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    peak_gap_roe: float = 0.0,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    peak = roe_pct(entry, best_price, lev)
    floors = _profit_lock_prices(
        entry, peak, lev, margin, entry_fee, funding_paid, include_plus10=peak_gap_roe > 0
    )
    if peak_gap_roe > 0:
        paper = best_price * (1.0 + trail_distance_pct(peak) / 100.0)
        stop = paper
        for floor in floors:
            stop = min(stop, floor)
        if peak >= peak_gap_roe:
            stop = min(stop, price_for_roe(entry, peak - peak_gap_roe, lev))
        return stop
    if peak < config.PAPER_BE_ARM_ROE:
        return liquidation_price(entry, lev)
    if peak < config.PAPER_LOCK_ARM_ROE:
        return min(floors) if floors else price_for_roe(entry, config.PAPER_BE_LOCK_NET_ROE, lev)
    lock_roe = max(config.PAPER_LOCK_MIN_ROE, peak - config.PAPER_TRAIL_GAP_ROE)
    stop = price_for_roe(entry, lock_roe, lev)
    for floor in floors:
        stop = min(stop, floor)
    return stop


def ema60_stretch_trail_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
    side: str = "short",
) -> float:
    """EMA60 stretch: −15% ROE, +5%→+2% ROE, +10%→+5% ROE, дальше трейл пик − 5 п.п. ROE."""
    lev = leverage or config.PAPER_LEVERAGE
    arm1 = config.PAPER_EMA60_STRETCH_LOCK1_ARM_ROE
    arm2 = config.PAPER_EMA60_STRETCH_LOCK2_ARM_ROE
    gap = config.PAPER_EMA60_STRETCH_TRAIL_GAP_ROE
    if side == "long":
        peak = long_roe_pct(entry, best_price, lev)
        initial = net_roe_stop_price_long(
            entry, margin, config.PAPER_EMA60_STRETCH_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
        )
        if peak < arm1:
            return initial
        stop = initial
        if peak >= arm1 and margin > 0:
            stop = max(
                stop,
                net_roe_stop_price_long(
                    entry, margin, config.PAPER_EMA60_STRETCH_LOCK1_ROE, lev, entry_fee, funding_paid
                ),
            )
        if peak >= arm2 and margin > 0:
            stop = max(
                stop,
                net_roe_stop_price_long(
                    entry, margin, config.PAPER_EMA60_STRETCH_LOCK2_ROE, lev, entry_fee, funding_paid
                ),
            )
            trail = price_for_long_roe(entry, peak - gap, lev)
            stop = max(stop, trail)
        return stop
    peak = roe_pct(entry, best_price, lev)
    initial = net_roe_stop_price(
        entry, margin, config.PAPER_EMA60_STRETCH_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
    )
    if peak < arm1:
        return initial
    stop = initial
    if peak >= arm1 and margin > 0:
        stop = min(
            stop,
            net_roe_stop_price(entry, margin, config.PAPER_EMA60_STRETCH_LOCK1_ROE, lev, entry_fee, funding_paid),
        )
    if peak >= arm2 and margin > 0:
        stop = min(
            stop,
            net_roe_stop_price(entry, margin, config.PAPER_EMA60_STRETCH_LOCK2_ROE, lev, entry_fee, funding_paid),
        )
        trail = price_for_roe(entry, peak - gap, lev)
        stop = min(stop, trail)
    return stop


def impulse_long_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Лонг Импульса: те же ступени ROE, что trail_stop у шорта Трейл 20."""
    lev = leverage or config.PAPER_LEVERAGE
    peak = long_roe_pct(entry, best_price, lev)
    floors: list[float] = []
    if peak >= config.PAPER_BE_ARM_ROE and margin > 0:
        floors.append(
            net_roe_stop_price_long(entry, margin, config.PAPER_BE_LOCK_NET_ROE, lev, entry_fee, funding_paid)
        )
    if peak < config.PAPER_BE_ARM_ROE:
        return long_liquidation_price(entry, lev)
    if peak < config.PAPER_LOCK_ARM_ROE:
        return max(floors) if floors else price_for_long_roe(entry, config.PAPER_BE_LOCK_NET_ROE, lev)
    lock_roe = max(config.PAPER_LOCK_MIN_ROE, peak - config.PAPER_TRAIL_GAP_ROE)
    stop = price_for_long_roe(entry, lock_roe, lev)
    for floor in floors:
        stop = max(stop, floor)
    return stop


@dataclass
class Position:
    """Общий счётчик для реальной виртуальной сделки и теневой (без баланса)."""

    symbol: str
    opened_at: int
    entry_price: float
    margin: float
    leverage: int = field(default_factory=lambda: config.PAPER_LEVERAGE)
    best_price: float = 0.0
    worst_price: float = 0.0
    stop_price: float = 0.0
    liq_price: float = 0.0
    entry_fee: float = 0.0
    funding_paid: float = 0.0
    next_funding_ts: int | None = None
    last_price: float = 0.0
    peak_gap_roe: float = 0.0
    loss_cap_armed: bool = False
    side: str = "short"
    stop_style: str = "default"
    scaled_half: bool = False
    desk_initial_stop: float = 0.0

    def __post_init__(self) -> None:
        if self.best_price <= 0:
            self.best_price = self.entry_price
        if self.worst_price <= 0:
            self.worst_price = self.entry_price
        if self.liq_price <= 0:
            self.liq_price = (
                long_liquidation_price(self.entry_price, self.leverage)
                if self.side == "long"
                else liquidation_price(self.entry_price, self.leverage)
            )
        if self.entry_fee <= 0:
            self.entry_fee = self.notional * config.PAPER_FEE_RATE_TAKER
        if self.stop_price <= 0:
            self._sync_stop(self.last_price if self.last_price > 0 else self.entry_price)
        if self.last_price <= 0:
            self.last_price = self.entry_price

    def _sync_stop(self, last: float) -> None:
        if self.stop_style == "css2":
            trail = css2_trail_stop(
                self.entry_price,
                self.best_price,
                self.leverage,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
                scaled_half=self.scaled_half,
            )
            self.stop_price = min(self.liq_price, trail)
            return
        if self.stop_style == "css":
            trail = css_trail_stop(
                self.entry_price,
                self.best_price,
                self.leverage,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
            )
            self.stop_price = min(self.liq_price, trail)
            return
        if self.stop_style == "sc10":
            trail = sc10_trail_stop(
                self.entry_price,
                self.best_price,
                self.leverage,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
                side=self.side,
            )
            if self.side == "long":
                self.stop_price = max(self.liq_price, trail)
            else:
                self.stop_price = min(self.liq_price, trail)
            return
        if self.stop_style == "e5s":
            trail = e5s_trail_stop(
                self.entry_price,
                self.best_price,
                self.leverage,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
            )
            self.stop_price = min(self.liq_price, trail)
            return
        if self.stop_style == "e5p":
            trail = e5p_trail_stop(
                self.entry_price,
                self.best_price,
                self.leverage,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
            )
            self.stop_price = min(self.liq_price, trail)
            return
        if self.stop_style == "ema_stretch":
            trail = ema60_stretch_trail_stop(
                self.entry_price,
                self.best_price,
                self.leverage,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
                side=self.side,
            )
            if self.side == "long":
                self.stop_price = max(self.liq_price, trail)
            else:
                self.stop_price = min(self.liq_price, trail)
            return
        if self.stop_style == "impulse":
            if self.side == "long":
                trail = impulse_long_stop(
                    self.entry_price,
                    self.best_price,
                    self.leverage,
                    margin=self.margin,
                    entry_fee=self.entry_fee,
                    funding_paid=self.funding_paid,
                )
                stop = max(self.liq_price, trail)
                if self.loss_cap_armed or self.gross_pnl(last) < 0:
                    self.loss_cap_armed = True
                    cap = net_roe_stop_price_long(
                        self.entry_price,
                        self.margin,
                        config.PAPER_LOSS_CAP_ROE,
                        self.leverage,
                        self.entry_fee,
                        self.funding_paid,
                    )
                    stop = max(stop, cap)
                self.stop_price = stop
                return
            trail = trail_stop(
                self.entry_price,
                self.best_price,
                self.leverage,
                0.0,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
            )
            stop = min(self.liq_price, trail)
            if self.loss_cap_armed or self.gross_pnl(last) < 0:
                self.loss_cap_armed = True
                cap = net_roe_stop_price(
                    self.entry_price,
                    self.margin,
                    config.PAPER_LOSS_CAP_ROE,
                    self.leverage,
                    self.entry_fee,
                    self.funding_paid,
                )
                stop = min(stop, cap)
            self.stop_price = stop
            return
        if self.stop_style == "mln":
            trail = mln_trail_stop(
                self.entry_price,
                self.best_price,
                self.leverage,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
            )
            self.stop_price = min(self.liq_price, trail)
            return
        if self.stop_style == "bab":
            if self.stop_price <= 0:
                self.stop_price = (
                    long_liquidation_price(self.entry_price, self.leverage)
                    if self.side == "long"
                    else liquidation_price(self.entry_price, self.leverage)
                )
            return
        if self.stop_style == "333":
            bab = self.desk_initial_stop if self.desk_initial_stop > 0 else self.stop_price
            if self.desk_initial_stop <= 0 and bab > 0:
                self.desk_initial_stop = bab
            if self.side == "long":
                trail = trail333_stop_long(
                    self.entry_price,
                    self.best_price,
                    bab,
                    self.leverage,
                    margin=self.margin,
                    entry_fee=self.entry_fee,
                    funding_paid=self.funding_paid,
                )
                self.stop_price = max(self.liq_price, trail)
            else:
                trail = trail333_stop_short(
                    self.entry_price,
                    self.best_price,
                    bab,
                    self.leverage,
                    margin=self.margin,
                    entry_fee=self.entry_fee,
                    funding_paid=self.funding_paid,
                )
                self.stop_price = min(self.liq_price, trail)
            return
        if self.stop_style == "pyl":
            trail = pyl_trail_stop(
                self.entry_price,
                self.best_price,
                self.leverage,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
            )
            stop = min(self.liq_price, trail)
            cap = net_roe_stop_price(
                self.entry_price,
                self.margin,
                config.PAPER_PYL_LOSS_CAP_ROE,
                self.leverage,
                self.entry_fee,
                self.funding_paid,
            )
            stop = min(stop, cap)
            if self.gross_pnl(last) < 0:
                self.loss_cap_armed = True
            self.stop_price = stop
            return
        if self.stop_style == "vps":
            if self.side == "long":
                trail = vps_trail_stop_long(
                    self.entry_price,
                    self.best_price,
                    self.leverage,
                    margin=self.margin,
                    entry_fee=self.entry_fee,
                    funding_paid=self.funding_paid,
                )
                self.stop_price = max(self.liq_price, trail)
            else:
                trail = vps_trail_stop_short(
                    self.entry_price,
                    self.best_price,
                    self.leverage,
                    margin=self.margin,
                    entry_fee=self.entry_fee,
                    funding_paid=self.funding_paid,
                )
                self.stop_price = min(self.liq_price, trail)
            return
        if self.side == "long":
            trail = trail_stop_long(
                self.entry_price,
                self.best_price,
                self.leverage,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
            )
            self.stop_price = max(self.liq_price, trail)
            return
        trail = trail_stop(
            self.entry_price,
            self.best_price,
            self.leverage,
            self.peak_gap_roe,
            margin=self.margin,
            entry_fee=self.entry_fee,
            funding_paid=self.funding_paid,
        )
        stop = min(self.liq_price, trail)
        if self.loss_cap_armed or self.gross_pnl(last) < 0:
            self.loss_cap_armed = True
            cap = net_roe_stop_price(
                self.entry_price,
                self.margin,
                config.PAPER_LOSS_CAP_ROE,
                self.leverage,
                self.entry_fee,
                self.funding_paid,
            )
            stop = min(stop, cap)
        self.stop_price = stop

    @property
    def notional(self) -> float:
        return self.margin * self.leverage

    @property
    def qty(self) -> float:
        return self.notional / self.entry_price

    def gross_pnl(self, price: float) -> float:
        if self.side == "long":
            return (price - self.entry_price) * self.qty
        return (self.entry_price - price) * self.qty

    def exit_fee(self, price: float) -> float:
        return self.qty * price * config.PAPER_FEE_RATE_TAKER

    def net_pnl(self, price: float) -> float:
        return self.gross_pnl(price) - self.entry_fee - self.exit_fee(price) + self.funding_paid

    def net_roe(self, price: float) -> float:
        return self.net_pnl(price) / self.margin * 100.0 if self.margin > 0 else 0.0

    def max_roe(self) -> float:
        if self.side == "long":
            return long_roe_pct(self.entry_price, self.best_price, self.leverage)
        return roe_pct(self.entry_price, self.best_price, self.leverage)

    def min_roe(self) -> float:
        if self.side == "long":
            return long_roe_pct(self.entry_price, self.worst_price, self.leverage)
        return roe_pct(self.entry_price, self.worst_price, self.leverage)

    def realize_half(self, price: float) -> float:
        """Закрыть половину шорта по цене. Маржа и комиссия входа делятся пополам."""
        if self.scaled_half or self.side != "short" or price <= 0 or self.margin <= 0:
            return 0.0
        fraction = 0.5
        gross = (self.entry_price - price) * self.qty * fraction
        exit_fee = self.qty * fraction * price * config.PAPER_FEE_RATE_TAKER
        entry_part = self.entry_fee * fraction
        funding_part = self.funding_paid * fraction
        pnl = gross - entry_part - exit_fee + funding_part
        self.entry_fee -= entry_part
        self.funding_paid -= funding_part
        self.margin *= 1.0 - fraction
        self.scaled_half = True
        self._sync_stop(price)
        return pnl

    def apply_funding(self, now_ms: int, rate: float | None, price: float) -> float:
        """Funding: шорт получает при rate>0, лонг платит."""
        if self.next_funding_ts is None or rate is None or now_ms < self.next_funding_ts:
            return 0.0
        payment = self.qty * price * rate
        if self.side == "long":
            payment = -payment
        self.funding_paid += payment
        self.next_funding_ts = None
        return payment

    def update(self, low: float, high: float, last: float) -> str | None:
        """Обновить по диапазону цен с прошлой проверки. Вернуть причину выхода."""
        self.last_price = last
        if self.side == "long":
            if low <= self.liq_price:
                self.worst_price = min(self.worst_price, self.liq_price)
                return "liquidation"
            if low <= self.stop_price:
                self.worst_price = min(self.worst_price, max(low, self.stop_price))
                return "trailing_stop"
            self.worst_price = min(self.worst_price, low)
            best_changed = high > self.best_price
            if best_changed:
                self.best_price = high
            prev_stop = self.stop_price
            self._sync_stop(last)
            if self.stop_price > prev_stop + 1e-12 and last <= self.stop_price:
                return "trailing_stop"
            return None
        if high >= self.liq_price:
            self.worst_price = max(self.worst_price, self.liq_price)
            return "liquidation"
        if high >= self.stop_price:
            self.worst_price = max(self.worst_price, min(high, self.stop_price))
            return "trailing_stop"
        self.worst_price = max(self.worst_price, high)
        best_changed = low < self.best_price
        if best_changed:
            self.best_price = low
        prev_stop = self.stop_price
        self._sync_stop(last)
        if self.stop_price < prev_stop - 1e-12 and last >= self.stop_price:
            return "trailing_stop"
        return None

    def close_result(self, reason: str) -> dict:
        """Итог закрытия. Ликвидация списывает всю маржу и комиссию входа."""
        if reason == "liquidation":
            price = self.liq_price
            exit_fee = 0.0
            pnl = -self.margin - self.entry_fee + self.funding_paid
        elif reason in ("opposite_pivot", "manual"):
            price = self.last_price if self.last_price > 0 else self.stop_price
            exit_fee = self.exit_fee(price)
            pnl = self.gross_pnl(price) - self.entry_fee - exit_fee + self.funding_paid
        else:
            price = self.stop_price
            exit_fee = self.exit_fee(price)
            pnl = self.gross_pnl(price) - self.entry_fee - exit_fee + self.funding_paid
        return {
            "exit_price": price,
            "exit_fee": exit_fee,
            "pnl_usd": pnl,
            "roe_pct": pnl / self.margin * 100.0 if self.margin > 0 else 0.0,
        }
