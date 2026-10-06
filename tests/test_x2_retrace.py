"""Доска 2× откат: min 5d, LH, стадии."""

from __future__ import annotations

import unittest

import config
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import lower_high_chain_count, pivot_highs
from signal_engine.pump_history import history_pump_metrics
from signal_engine.x2_retrace import stage_for


def _bar(ts: int, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(ts, o, h, l, c, 1.0, from_kline=True)


class X2RetraceTests(unittest.TestCase):
    def test_history_pump_7d(self) -> None:
        state = SymbolState("TESTUSDT")
        state.last_price = 20.0
        state.turnover_24h_usdt = config.UNIVERSE_MIN_TURNOVER_24H_USDT
        now = 1_700_000_000_000
        bars = []
        for i in range(120):
            ts = now - (120 - i) * 3_600_000
            low = 8.0 if i < 60 else 10.0
            high = 22.0 if 50 <= i < 70 else low + 1
            bars.append(_bar(ts, low, high, low, low + 0.5))
        state.bars_htf["60"] = bars
        hist = history_pump_metrics(state, now)
        self.assertIsNotNone(hist)
        assert hist is not None
        self.assertGreaterEqual(hist.peak_mult, 2.0)
        self.assertAlmostEqual(hist.min_low, 8.0)

    def test_lower_high_chain(self) -> None:
        now = 2_000_000_000_000
        bars = []
        ts = now - 50 * 3_600_000
        pattern = [(100, 110), (105, 108), (102, 104), (98, 100)]
        for o, h in pattern:
            bars.append(_bar(ts, o, h, o - 2, o))
            ts += 3_600_000
        for _ in range(40):
            bars.append(_bar(ts, 90, 92, 88, 90))
            ts += 3_600_000
        peaks = pivot_highs(bars, wing=2)
        self.assertGreaterEqual(len(peaks), 2)
        pump_start = bars[0].timestamp
        count = lower_high_chain_count(bars, pump_start, "60", now, wing=2)
        self.assertGreaterEqual(count, 1)

    def test_stage_progression(self) -> None:
        self.assertEqual(stage_for(multiplier=2.1, pullback_ok=False, lh_1h=0, lh_4h=0, oi_drop=False, ema_depth=0), 1)
        self.assertEqual(stage_for(multiplier=2.1, pullback_ok=True, lh_1h=0, lh_4h=0, oi_drop=False, ema_depth=0), 2)
        self.assertEqual(stage_for(multiplier=2.1, pullback_ok=True, lh_1h=2, lh_4h=0, oi_drop=False, ema_depth=0), 2)
        self.assertEqual(stage_for(multiplier=2.1, pullback_ok=True, lh_1h=2, lh_4h=0, oi_drop=True, ema_depth=1), 3)
        self.assertEqual(stage_for(multiplier=2.1, pullback_ok=True, lh_1h=2, lh_4h=1, oi_drop=True, ema_depth=2), 4)


if __name__ == "__main__":
    unittest.main()
