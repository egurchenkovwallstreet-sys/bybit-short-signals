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
        from signal_engine.state import Bar

        now_ms = 1_700_000_000_000
        state = SymbolState("TESTUSDT")
        state.turnover_24h_usdt = config.PUMP_UNIFIED_MIN_TURNOVER_USDT
        step = 15 * 60_000
        for i in range(96):
            ts = now_ms - (95 - i) * step
            low = 100.0 if i < 48 else 100.0 + (i - 48) * 0.8
            high = low + 1.0
            state.bars_htf.setdefault("15", []).append(Bar(ts, low, high, low, low, 5000.0))
        state.price_24h_change = 0.34
        self.assertFalse(is_gainer_candidate(state, now_ms))
        state.price_24h_change = 0.35
        for i in range(48, 96):
            bar = state.bars_htf["15"][i]
            state.bars_htf["15"][i] = Bar(
                bar.timestamp, bar.open, bar.high + 0.5, bar.low, bar.close + 0.5, 8000.0
            )
        self.assertTrue(is_gainer_candidate(state, now_ms))

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
