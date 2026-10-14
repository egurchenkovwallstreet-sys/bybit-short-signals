"""Молния: −10% ROE, +2.5%→+2%, +6%→+4%, +7%→+5%, дальше трейл пик − 20 п.п."""

from __future__ import annotations

import unittest

from signal_engine.paper.position import Position, mln_trail_stop, net_roe_stop_price, price_for_roe


class MlnStopTest(unittest.TestCase):
    def test_initial_stop_is_minus_10(self) -> None:
        stop = mln_trail_stop(1.0, 0.999, 10, margin=50.0, entry_fee=0.0275)
        initial = net_roe_stop_price(1.0, 50.0, -10.0, 10, 0.0275, 0.0)
        self.assertAlmostEqual(stop, initial, places=6)

    def test_plus_2_5_moves_stop_to_plus_2(self) -> None:
        best = price_for_roe(1.0, 2.5, 10)
        stop = mln_trail_stop(1.0, best, 10, margin=50.0, entry_fee=0.0275)
        self.assertAlmostEqual(stop, price_for_roe(1.0, 2.0, 10), places=6)

    def test_plus_6_moves_stop_to_plus_4(self) -> None:
        best = price_for_roe(1.0, 6.0, 10)
        stop = mln_trail_stop(1.0, best, 10, margin=50.0, entry_fee=0.0275)
        self.assertAlmostEqual(stop, price_for_roe(1.0, 4.0, 10), places=6)

    def test_plus_7_moves_stop_to_plus_5(self) -> None:
        best = price_for_roe(1.0, 7.0, 10)
        stop = mln_trail_stop(1.0, best, 10, margin=50.0, entry_fee=0.0275)
        self.assertAlmostEqual(stop, price_for_roe(1.0, 5.0, 10), places=6)

    def test_trail_follows_twenty_points_behind_peak(self) -> None:
        best = price_for_roe(1.0, 30.0, 10)
        stop = mln_trail_stop(1.0, best, 10, margin=50.0, entry_fee=0.0275)
        self.assertAlmostEqual(stop, price_for_roe(1.0, 10.0, 10), places=6)
        self.assertLess(stop, price_for_roe(1.0, 5.0, 10))

    def test_position_steps_the_stop(self) -> None:
        pos = Position("X", 0, 1.0, 50.0, stop_style="mln")
        initial = net_roe_stop_price(1.0, 50.0, -10.0, 10, pos.entry_fee, 0.0)
        self.assertAlmostEqual(pos.stop_price, initial, places=5)
        best = price_for_roe(1.0, 2.5, 10)
        self.assertIsNone(pos.update(best, 1.0, best))
        self.assertAlmostEqual(pos.stop_price, price_for_roe(1.0, 2.0, 10), places=5)
        deeper = price_for_roe(1.0, 7.0, 10)
        self.assertIsNone(pos.update(deeper, best, deeper))
        self.assertAlmostEqual(pos.stop_price, price_for_roe(1.0, 5.0, 10), places=5)


if __name__ == "__main__":
    unittest.main()
