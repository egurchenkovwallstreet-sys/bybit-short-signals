import config
from signal_engine.paper.position import (
    bab_pivot_stop_price,
    long_roe_pct,
    net_roe_stop_price,
    price_for_roe,
    roe_pct,
    trail333_stop_long,
    trail333_stop_short,
)

MARGIN = 50.0
FEE = 0.0275


def test_trail333_short_before_arm_keeps_bab():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    bab = bab_pivot_stop_price("short", pivot_high=101.0, pivot_low=99.0, leverage=lev)
    best = entry * (1.0 - 4.0 / (100.0 * lev))
    assert roe_pct(entry, best, lev) < config.PAPER_333_TRAIL_ARM_ROE
    assert (
        trail333_stop_short(entry, best, bab, lev, margin=MARGIN, entry_fee=FEE)
        == bab
    )


def test_trail333_short_arm_locks_net_half():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    bab = bab_pivot_stop_price("short", pivot_high=101.0, pivot_low=99.0, leverage=lev)
    best = entry * (1.0 - 6.0 / (100.0 * lev))
    stop = trail333_stop_short(entry, best, bab, lev, margin=MARGIN, entry_fee=FEE)
    lock = net_roe_stop_price(
        entry, MARGIN, config.PAPER_333_TRAIL_LOCK_NET_ROE, lev, FEE, 0.0
    )
    assert abs(stop - lock) < 1e-9


def test_trail333_short_trail_follows_peak():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    bab = bab_pivot_stop_price("short", pivot_high=101.0, pivot_low=99.0, leverage=lev)
    best = entry * (1.0 - 25.0 / (100.0 * lev))
    stop = trail333_stop_short(entry, best, bab, lev, margin=MARGIN, entry_fee=FEE)
    peak = roe_pct(entry, best, lev)
    lock = net_roe_stop_price(
        entry, MARGIN, config.PAPER_333_TRAIL_LOCK_NET_ROE, lev, FEE, 0.0
    )
    trail = min(
        price_for_roe(entry, peak - config.PAPER_333_TRAIL_GAP_ROE, lev),
        lock,
        price_for_roe(entry, config.PAPER_333_LOCK10_ROE, lev),
    )
    assert abs(stop - min(trail, bab)) < 0.0001


def test_trail333_short_lock5_at_peak_10():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    bab = bab_pivot_stop_price("short", pivot_high=101.0, pivot_low=99.0, leverage=lev)
    best = entry * (1.0 - 11.0 / (100.0 * lev))
    stop = trail333_stop_short(entry, best, bab, lev, margin=MARGIN, entry_fee=FEE)
    assert abs(stop - price_for_roe(entry, config.PAPER_333_LOCK5_ROE, lev)) < 1e-9


def test_trail333_long_before_arm_keeps_bab():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    bab = bab_pivot_stop_price("long", pivot_high=101.0, pivot_low=99.0, leverage=lev)
    best = entry * (1.0 + 4.0 / (100.0 * lev))
    assert long_roe_pct(entry, best, lev) < config.PAPER_333_TRAIL_ARM_ROE
    assert trail333_stop_long(entry, best, bab, lev, margin=MARGIN, entry_fee=FEE) == bab
