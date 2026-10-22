"""EMA6 Bybit trailing: −10% ROE, arm +2% → −5% ROE."""

from __future__ import annotations

import unittest

import config
from signal_engine.live.em6_bybit.stops import (
    em6_bybit_active_trail_roe_pct,
    trailing_stop_distance_price,
)


class TestEm6BybitTrail(unittest.TestCase):
    def test_initial_trail_10(self) -> None:
        self.assertAlmostEqual(config.em6_bybit_trail_initial_roe(), 10.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(0.0), 10.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(1.9), 10.0)

    def test_tight_trail_after_arm(self) -> None:
        self.assertAlmostEqual(config.em6_bybit_trail_arm_roe(), 2.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(2.0), 5.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(20.0), 5.0)

    def test_distance_scales_with_roe(self) -> None:
        p = 100.0
        d10 = trailing_stop_distance_price(p, 10.0)
        d5 = trailing_stop_distance_price(p, 5.0)
        self.assertAlmostEqual(d5, d10 / 2.0, places=6)


if __name__ == "__main__":
    unittest.main()
