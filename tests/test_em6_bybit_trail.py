"""EMA6 Bybit: trailing-only лестница."""

from __future__ import annotations

import unittest

import config
from signal_engine.live.em6_bybit.stops import (
    em6_bybit_active_trail_roe_pct,
    em6_bybit_initial_trail_roe_pct,
    em6_bybit_ladder_trail_gap_candidate,
    normalize_locked_trail_gap,
    trail_roe_pct_from_trailing_distance,
    trailing_stop_distance_price,
)


class TestEm6BybitTrail(unittest.TestCase):
    def test_wide_before_20(self) -> None:
        self.assertAlmostEqual(em6_bybit_ladder_trail_gap_candidate(10.0), 50.0)

    def test_mid_at_20(self) -> None:
        self.assertAlmostEqual(em6_bybit_ladder_trail_gap_candidate(20.0), 15.0)

    def test_tight_at_50(self) -> None:
        self.assertAlmostEqual(em6_bybit_ladder_trail_gap_candidate(50.0), 10.0)

    def test_ratchet_on_pullback(self) -> None:
        self.assertAlmostEqual(
            em6_bybit_active_trail_roe_pct(30.0, locked_trail_gap_roe=10.0),
            10.0,
        )

    def test_normalize_legacy_lock(self) -> None:
        self.assertAlmostEqual(normalize_locked_trail_gap(5.0), 50.0)
        self.assertAlmostEqual(normalize_locked_trail_gap(15.0), 15.0)

    def test_trail_distance_roundtrip(self) -> None:
        mark = 0.021359
        dist = trailing_stop_distance_price(mark, 15.0)
        back = trail_roe_pct_from_trailing_distance(mark, dist)
        self.assertAlmostEqual(back, 15.0, places=1)

    def test_thresholds(self) -> None:
        self.assertAlmostEqual(config.em6_bybit_trail_profit_arm_roe(), 20.0)
        self.assertAlmostEqual(config.em6_bybit_trail_tight_arm_roe(), 50.0)
        self.assertAlmostEqual(config.em6_bybit_trail_mid_dist_roe(), 15.0)
        self.assertAlmostEqual(em6_bybit_initial_trail_roe_pct(), 50.0)


if __name__ == "__main__":
    unittest.main()
