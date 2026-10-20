import config
from signal_engine.paper.position import (
    net_roe_stop_price,
    net_roe_stop_price_long,
    roe_pct,
    long_roe_pct,
    trail333_initial_stop,
    trail333_stop_long,
    trail333_stop_short,
)

MARGIN = 50.0
FEE = 0.0275


def test_trail333_short_before_arm_uses_minus_10():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    best = entry * (1.0 - 2.0 / (100.0 * lev))
    assert roe_pct(entry, best, lev) < config.PAPER_333_TRAIL_ARM_ROE
    want = trail333_initial_stop("short", entry, lev, margin=MARGIN, entry_fee=FEE)
    assert trail333_stop_short(entry, best, 999.0, lev, margin=MARGIN, entry_fee=FEE) == want


def test_trail333_short_arm_locks_net():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    best = entry * (1.0 - 3.0 / (100.0 * lev))
    stop = trail333_stop_short(entry, best, 999.0, lev, margin=MARGIN, entry_fee=FEE)
    lock = net_roe_stop_price(
        entry, MARGIN, config.PAPER_333_TRAIL_LOCK_NET_ROE, lev, FEE, 0.0
    )
    trail = best * (1.0 + config.PAPER_333_TRAIL_FROM_PRICE_ROE / (100.0 * lev))
    assert abs(stop - min(lock, trail)) < 1e-9


def test_trail333_short_trail_from_best():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    best = entry * (1.0 - 30.0 / (100.0 * lev))
    stop = trail333_stop_short(entry, best, 999.0, lev, margin=MARGIN, entry_fee=FEE)
    lock = net_roe_stop_price(
        entry, MARGIN, config.PAPER_333_TRAIL_LOCK_NET_ROE, lev, FEE, 0.0
    )
    trail = best * (1.0 + config.PAPER_333_TRAIL_FROM_PRICE_ROE / (100.0 * lev))
    assert abs(stop - min(lock, trail)) < 0.0001


def test_trail333_long_before_arm_uses_minus_10():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    best = entry * (1.0 + 2.0 / (100.0 * lev))
    assert long_roe_pct(entry, best, lev) < config.PAPER_333_TRAIL_ARM_ROE
    want = trail333_initial_stop("long", entry, lev, margin=MARGIN, entry_fee=FEE)
    assert trail333_stop_long(entry, best, 0.0, lev, margin=MARGIN, entry_fee=FEE) == want


def test_trail333_long_arm():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    best = entry * (1.0 + 5.0 / (100.0 * lev))
    stop = trail333_stop_long(entry, best, 0.0, lev, margin=MARGIN, entry_fee=FEE)
    lock = net_roe_stop_price_long(
        entry, MARGIN, config.PAPER_333_TRAIL_LOCK_NET_ROE, lev, FEE, 0.0
    )
    trail = best * (1.0 - config.PAPER_333_TRAIL_FROM_PRICE_ROE / (100.0 * lev))
    assert abs(stop - max(lock, trail)) < 1e-9
