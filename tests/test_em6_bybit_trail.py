"""EMA6 Bybit trailing ladder: −50% ROE, +10% peak → −40%, …"""

from __future__ import annotations

import unittest

import config
from signal_engine.live.em6_bybit.stops import (
    em6_bybit_active_trail_roe_pct,
    trailing_stop_distance_price,
)


class TestEm6BybitTrail(unittest.TestCase):
    def test_initial_trail_50(self) -> None:
        self.assertAlmostEqual(config.em6_bybit_trail_initial_roe(), 50.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(0.0), 50.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(9.9), 50.0)

    def test_ladder_tightens_every_10_peak(self) -> None:
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(10.0), 40.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(19.9), 40.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(20.0), 30.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(30.0), 20.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(40.0), 10.0)
        self.assertAlmostEqual(em6_bybit_active_trail_roe_pct(50.0), 10.0)

    def test_distance_scales_with_roe(self) -> None:
        p = 100.0
        d50 = trailing_stop_distance_price(p, 50.0)
        d40 = trailing_stop_distance_price(p, 40.0)
        self.assertAlmostEqual(d40, d50 * 0.8, places=6)


if __name__ == "__main__":
    unittest.main()
