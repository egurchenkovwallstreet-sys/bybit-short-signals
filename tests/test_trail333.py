import config
from signal_engine.paper.position import (
    bab_pivot_stop_price,
    long_roe_pct,
    roe_pct,
    trail333_stop_long,
    trail333_stop_short,
)


def test_trail333_short_before_arm_keeps_bab():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    bab = bab_pivot_stop_price("short", pivot_high=101.0, pivot_low=99.0, leverage=lev)
    best = entry * (1.0 - 4.0 / (100.0 * lev))
    assert roe_pct(entry, best, lev) < config.PAPER_333_TRAIL_ARM_ROE
    assert trail333_stop_short(entry, best, bab, lev) == bab


def test_trail333_short_arm_locks_plus_one():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    bab = bab_pivot_stop_price("short", pivot_high=101.0, pivot_low=99.0, leverage=lev)
    best = entry * (1.0 - 6.0 / (100.0 * lev))
    stop = trail333_stop_short(entry, best, bab, lev)
    assert roe_pct(entry, stop, lev) >= config.PAPER_333_TRAIL_LOCK_ROE - 0.01


def test_trail333_short_trail_follows_peak():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    bab = bab_pivot_stop_price("short", pivot_high=101.0, pivot_low=99.0, leverage=lev)
    best = entry * (1.0 - 25.0 / (100.0 * lev))
    stop = trail333_stop_short(entry, best, bab, lev)
    peak = roe_pct(entry, best, lev)
    lock = max(config.PAPER_333_TRAIL_LOCK_ROE, peak - config.PAPER_333_TRAIL_GAP_ROE)
    assert abs(roe_pct(entry, stop, lev) - lock) < 0.05


def test_trail333_long_before_arm_keeps_bab():
    entry = 100.0
    lev = config.PAPER_LEVERAGE
    bab = bab_pivot_stop_price("long", pivot_high=101.0, pivot_low=99.0, leverage=lev)
    best = entry * (1.0 + 4.0 / (100.0 * lev))
    assert long_roe_pct(entry, best, lev) < config.PAPER_333_TRAIL_ARM_ROE
    assert trail333_stop_long(entry, best, bab, lev) == bab
