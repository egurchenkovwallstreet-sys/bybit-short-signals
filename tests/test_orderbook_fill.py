"""Стакан: исполнение не более чем в 3 уровнях."""

from __future__ import annotations

import unittest

from signal_engine.paper.orderbook_fill import simulate_market_fill


class OrderbookFillTest(unittest.TestCase):
    def test_buy_fits_three_levels(self) -> None:
        asks = {100.0: 1.0, 100.5: 1.0, 101.0: 10.0}
        bids = {99.0: 5.0}
        r = simulate_market_fill("buy", 2.0, bids, asks, max_levels=3, ref_price=100.0)
        self.assertTrue(r.ok)
        self.assertEqual(r.levels_used, 2)
        self.assertAlmostEqual(r.avg_price, (100.0 + 100.5) / 2, places=4)

    def test_reject_fourth_level(self) -> None:
        asks = {100.0: 0.1, 101.0: 0.1, 102.0: 0.1, 103.0: 100.0}
        bids: dict[float, float] = {}
        r = simulate_market_fill("buy", 1.0, bids, asks, max_levels=3, ref_price=100.0)
        self.assertFalse(r.ok)
        self.assertIn("levels", r.reason or "")

    def test_insufficient_size_in_three_levels(self) -> None:
        asks = {100.0: 0.01, 101.0: 0.01}
        r = simulate_market_fill("buy", 1.0, {}, asks, max_levels=3)
        self.assertFalse(r.ok)


if __name__ == "__main__":
    unittest.main()
