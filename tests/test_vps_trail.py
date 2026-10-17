"""Пылесос 5/15: сразу −15% net, дальше ступени Трейл 20."""

from __future__ import annotations

import unittest

import config
from signal_engine.paper.position import (
    liquidation_price,
    long_liquidation_price,
    net_roe_stop_price,
    net_roe_stop_price_long,
    price_for_roe,
    vps_trail_stop_long,
    vps_trail_stop_short,
)


class VpsTrailTest(unittest.TestCase):
    def test_short_starts_at_minus_15_inside_liquidation(self) -> None:
        entry = 100.0
        stop = vps_trail_stop_short(entry, entry, leverage=10, margin=50.0, entry_fee=0.0)
        target = net_roe_stop_price(entry, 50.0, config.PAPER_VPS_INITIAL_STOP_ROE, 10, 0.0, 0.0)
        self.assertAlmostEqual(stop, target)
        self.assertGreater(stop, entry)
        self.assertLess(stop, liquidation_price(entry, 10))

    def test_short_holds_initial_until_plus_3(self) -> None:
        entry = 100.0
        initial = vps_trail_stop_short(entry, entry, leverage=10, margin=50.0, entry_fee=0.0)
        best = price_for_roe(entry, 2.0, 10)
        stop = vps_trail_stop_short(entry, best, leverage=10, margin=50.0, entry_fee=0.0)
        self.assertAlmostEqual(stop, initial)

    def test_short_locks_half_net_from_plus_3_and_five_from_plus_7(self) -> None:
        entry = 100.0
        at4 = vps_trail_stop_short(entry, price_for_roe(entry, 4.0, 10), leverage=10, margin=50.0, entry_fee=0.0)
        lock = net_roe_stop_price(entry, 50.0, config.PAPER_BE_LOCK_NET_ROE, 10, 0.0, 0.0)
        self.assertAlmostEqual(at4, lock)
        self.assertLess(at4, entry)
        at8 = vps_trail_stop_short(entry, price_for_roe(entry, 8.0, 10), leverage=10, margin=50.0, entry_fee=0.0)
        self.assertAlmostEqual(at8, price_for_roe(entry, 5.0, 10))
        at30 = vps_trail_stop_short(entry, price_for_roe(entry, 30.0, 10), leverage=10, margin=50.0, entry_fee=0.0)
        self.assertAlmostEqual(at30, price_for_roe(entry, 10.0, 10))

    def test_long_starts_at_minus_15_inside_liquidation(self) -> None:
        entry = 100.0
        stop = vps_trail_stop_long(entry, entry, leverage=10, margin=50.0, entry_fee=0.0)
        target = net_roe_stop_price_long(entry, 50.0, config.PAPER_VPS_INITIAL_STOP_ROE, 10, 0.0, 0.0)
        self.assertAlmostEqual(stop, target)
        self.assertLess(stop, entry)
        self.assertGreater(stop, long_liquidation_price(entry, 10))

    def test_short_trail_follows_peak(self) -> None:
        entry = 100.0
        stop_flat = vps_trail_stop_short(entry, 95.0, leverage=10, margin=50.0)
        stop_deeper = vps_trail_stop_short(entry, 90.0, leverage=10, margin=50.0)
        self.assertLess(stop_deeper, stop_flat)

    def test_long_trail_follows_peak(self) -> None:
        entry = 100.0
        stop_small = vps_trail_stop_long(entry, 105.0, leverage=10, margin=50.0)
        stop_big = vps_trail_stop_long(entry, 110.0, leverage=10, margin=50.0)
        self.assertGreater(stop_big, stop_small)


if __name__ == "__main__":
    unittest.main()
