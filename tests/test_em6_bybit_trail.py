"""EMA6 Bybit trailing: −50% → +20%/+5% lock → +50%/+10% dist."""

from __future__ import annotations

import unittest

import config
from signal_engine.live.em6_bybit.stops import (
    em6_bybit_active_trail_roe_pct,
    trail_roe_pct_from_trailing_distance,
    trailing_stop_distance_price,
)


class TestEm6BybitTrail(unittest.TestCase):
    def test_wide_until_plus_20(self) -> None:
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(0.0), 50.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(19.9), 50.0)

    def test_profit_phase_follows_price(self) -> None:
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(20.0), 15.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(30.0), 25.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(49.0), 44.0)

    def test_tight_after_plus_50(self) -> None:
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(50.0), 10.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(80.0), 10.0)

    def test_arm_threshold(self) -> None:
        self.assertAlmostEqual(config.em6_bybit_trail_profit_arm_roe(), 20.0)
        self.assertAlmostEqual(config.em6_bybit_trail_lock_roe(), 5.0)

    def test_trail_distance_roundtrip(self) -> None:
        mark = 0.021359
        dist = trailing_stop_distance_price(mark, 15.0)
        back = trail_roe_pct_from_trailing_distance(mark, dist)
        self.assertAlmostEqual(back, 15.0, places=1)


if __name__ == "__main__":
    unittest.main()
