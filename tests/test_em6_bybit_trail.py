"""EMA6 Bybit: лестница стопа."""

from __future__ import annotations

import unittest

import config
from signal_engine.live.em6_bybit.stops import (
    em6_bybit_initial_trail_roe_pct,
    em6_bybit_ladder_target_stop_roe,
    em6_bybit_use_tight_trail,
    trail_roe_pct_from_trailing_distance,
    trailing_stop_distance_price,
)


class TestEm6BybitTrail(unittest.TestCase):
    def test_wide_before_20(self) -> None:
        self.assertIsNone(em6_bybit_ladder_target_stop_roe(10.0, 10.0))
        self.assertAlmostEqual(em6_bybit_initial_trail_roe_pct(), 50.0)

    def test_lock_at_20(self) -> None:
        self.assertAlmostEqual(em6_bybit_ladder_target_stop_roe(20.0, 20.0), 5.0)

    def test_max_minus_10_at_40(self) -> None:
        self.assertAlmostEqual(em6_bybit_ladder_target_stop_roe(40.0, 42.0), 32.0)

    def test_trail_5_at_60(self) -> None:
        self.assertTrue(em6_bybit_use_tight_trail(60.0))
        self.assertAlmostEqual(em6_bybit_ladder_target_stop_roe(60.0, 65.0), 55.0)

    def test_ladder_takes_max(self) -> None:
        self.assertAlmostEqual(em6_bybit_ladder_target_stop_roe(45.0, 48.0), 38.0)

    def test_trail_distance_roundtrip(self) -> None:
        mark = 0.021359
        dist = trailing_stop_distance_price(mark, 15.0)
        back = trail_roe_pct_from_trailing_distance(mark, dist)
        self.assertAlmostEqual(back, 15.0, places=1)

    def test_thresholds(self) -> None:
        self.assertAlmostEqual(config.em6_bybit_trail_profit_arm_roe(), 20.0)
        self.assertAlmostEqual(config.EM6_BYBIT_LADDER_ROE_2, 40.0)
        self.assertAlmostEqual(config.EM6_BYBIT_LADDER_ROE_3, 60.0)


if __name__ == "__main__":
    unittest.main()
