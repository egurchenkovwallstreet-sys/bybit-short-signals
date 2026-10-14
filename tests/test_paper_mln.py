"""Молния: вход как t20/p10, стоп −10% ROE, с +2% чистый BE, с +7% трейл 3 п.п."""

from __future__ import annotations

import unittest

from signal_engine.paper.position import (
    Position,
    mln_trail_stop,
    net_breakeven_stop_price,
    net_roe_stop_price,
    price_for_roe,
)


class MlnStopTest(unittest.TestCase):
    def test_initial_stop_is_minus_10(self) -> None:
        stop = mln_trail_stop(1.0, 0.999, 10, margin=50.0, entry_fee=0.0275)
        initial = net_roe_stop_price(1.0, 50.0, -10.0, 10, 0.0275, 0.0)
        self.assertAlmostEqual(stop, initial, places=6)

    def test_breakeven_from_plus_2_until_plus_7(self) -> None:
        be = net_breakeven_stop_price(1.0, 50.0, 10, 0.0275, 0.0)
        # +2% ROE при ×10 = цена 0.998; +6% = 0.994
        at_two = mln_trail_stop(1.0, 0.998, 10, margin=50.0, entry_fee=0.0275)
        at_six = mln_trail_stop(1.0, 0.994, 10, margin=50.0, entry_fee=0.0275)
        self.assertAlmostEqual(at_two, be, places=6)
        self.assertAlmostEqual(at_six, be, places=6)

    def test_plus_7_uses_tighter_of_floor_and_trail(self) -> None:
        floor = net_roe_stop_price(1.0, 50.0, 3.0, 10, 0.0275, 0.0)
        trailed = price_for_roe(1.0, 4.0, 10)
        stop = mln_trail_stop(1.0, 0.993, 10, margin=50.0, entry_fee=0.0275)
        self.assertAlmostEqual(stop, min(floor, trailed), places=6)
        self.assertLessEqual(stop, floor)

    def test_trail_follows_three_points_behind_peak(self) -> None:
        # пик +15% ROE → трейл +12% gross, это жёстче пола +3% net
        best = price_for_roe(1.0, 15.0, 10)
        trailed = price_for_roe(1.0, 12.0, 10)
        floor = net_roe_stop_price(1.0, 50.0, 3.0, 10, 0.0275, 0.0)
        stop = mln_trail_stop(1.0, best, 10, margin=50.0, entry_fee=0.0275)
        self.assertAlmostEqual(stop, trailed, places=6)
        self.assertLess(stop, floor)

    def test_position_arms_be_then_trail(self) -> None:
        pos = Position("X", 0, 1.0, 50.0, stop_style="mln")
        initial = net_roe_stop_price(1.0, 50.0, -10.0, 10, pos.entry_fee, 0.0)
        self.assertAlmostEqual(pos.stop_price, initial, places=5)
        self.assertIsNone(pos.update(0.998, 1.0, 0.998))
        be = net_breakeven_stop_price(1.0, 50.0, 10, pos.entry_fee, 0.0)
        self.assertAlmostEqual(pos.stop_price, be, places=5)
        self.assertIsNone(pos.update(0.993, pos.stop_price - 0.0001, 0.993))
        floor = net_roe_stop_price(1.0, 50.0, 3.0, 10, pos.entry_fee, 0.0)
        self.assertLessEqual(pos.stop_price, floor + 1e-9)


if __name__ == "__main__":
    unittest.main()
