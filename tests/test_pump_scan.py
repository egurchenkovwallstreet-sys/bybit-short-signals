"""Памп-скан и пробой EMA."""

from __future__ import annotations

import unittest

import config
from signal_engine.ema_breakdown import analyze_ema_breakdown
from signal_engine.indicators import ema
from signal_engine.pump_scan import is_gainer_candidate, price_24h_pct, stage_for
from signal_engine.evaluate import Reading
from signal_engine.state import SymbolState


class PumpScanTests(unittest.TestCase):
    def test_price_24h_ratio_to_percent(self) -> None:
        self.assertAlmostEqual(price_24h_pct(0.42), 42.0)
        self.assertAlmostEqual(price_24h_pct(42.0), 42.0)

    def test_gainer_threshold(self) -> None:
        state = SymbolState("TESTUSDT")
        state.turnover_24h_usdt = config.UNIVERSE_MIN_TURNOVER_24H_USDT
        state.price_24h_change = 0.34
        self.assertFalse(is_gainer_candidate(state))
        state.price_24h_change = 0.35
        self.assertTrue(is_gainer_candidate(state))

    def test_stage_progression(self) -> None:
        state = SymbolState("X")
        reading = Reading()
        self.assertEqual(stage_for(reading, state, 0, {}), 1)
        reading.liquidations_faded = True
        self.assertEqual(stage_for(reading, state, 0, {"15m": {"depth": 1}}), 2)
        reading.oi_drop = True
        reading.volume_faded = True
        self.assertEqual(stage_for(reading, state, 0, {"15m": {"depth": 2}}), 3)

    def test_ema_breakdown_depth(self) -> None:
        closes = [100.0 + i * 0.1 for i in range(250)]
        closes[-1] = 80.0
        closes[-2] = 95.0
        series50 = ema(closes, 50)
        self.assertIsNotNone(series50[-1])
        result = analyze_ema_breakdown(closes)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreaterEqual(result.depth, 1)


if __name__ == "__main__":
    unittest.main()
