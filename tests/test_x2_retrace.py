"""Доска 2× откат: min 5d, LH, стадии."""

from __future__ import annotations

import unittest

import config
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import lower_high_chain_count, pivot_highs
from signal_engine.pump_history import history_pump_metrics
from signal_engine.x2_retrace import (
    _pump_leg_volume_spike_ok,
    candidate_stage as stage_for,
    price_change_7d_pct,
)


def _bar(ts: int, o: float, h: float, l: float, c: float, vol: float = 1.0) -> Bar:
    return Bar(ts, o, h, l, c, vol, from_kline=True)


class X2RetraceTests(unittest.TestCase):
    def test_history_pump_7d(self) -> None:
        state = SymbolState("TESTUSDT")
        state.last_price = 20.0
        state.turnover_24h_usdt = config.X2_RETRACE_MIN_TURNOVER_24H_USDT
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

    def test_price_change_7d_positive(self) -> None:
        now = 3_000_000_000_000
        state = SymbolState("UPUSDT")
        bars = []
        ts = now - 10 * 86_400_000
        for i in range(10):
            close = 10.0 + i * 0.5
            bars.append(_bar(ts, close, close + 0.2, close - 0.2, close))
            ts += 86_400_000
        state.bars_htf["D"] = bars
        pct = price_change_7d_pct(state, now)
        self.assertIsNotNone(pct)
        assert pct is not None
        self.assertGreater(pct, 0)

    def test_pump_volume_spike(self) -> None:
        now = 4_000_000_000_000
        valley = now - 30 * 3_600_000
        bars = []
        ts = valley - 10 * 3_600_000
        for _ in range(10):
            bars.append(_bar(ts, 1, 1.1, 0.9, 1, vol=5.0))
            ts += 3_600_000
        for i in range(12):
            vol = 50.0 if i == 6 else 5.0
            bars.append(_bar(ts, 1 + i * 0.1, 1.2 + i * 0.1, 0.9, 1 + i * 0.1, vol=vol))
            ts += 3_600_000
        self.assertTrue(_pump_leg_volume_spike_ok(bars, valley, now))

    def test_stage_progression(self) -> None:
        from signal_engine.swing_highs import TwoPeakMatch

        self.assertEqual(
            stage_for(peak_mult=2.1, pullback_ok=False, two_peak=None, lh_1h=0, lh_4h=0, oi_drop=False, ema_depth=0),
            0,
        )

        peak = TwoPeakMatch("lower_high", "60", 10.0, 9.0, 6, 1, 2)
        self.assertEqual(
            stage_for(
                peak_mult=2.1,
                pullback_ok=True,
                two_peak=peak,
                lh_1h=0,
                lh_4h=0,
                oi_drop=False,
                ema_depth=0,
            ),
            2,
        )
        self.assertEqual(
            stage_for(
                peak_mult=2.1,
                pullback_ok=True,
                two_peak=peak,
                lh_1h=2,
                lh_4h=0,
                oi_drop=True,
                ema_depth=1,
            ),
            3,
        )
        self.assertEqual(
            stage_for(
                peak_mult=2.1,
                pullback_ok=True,
                two_peak=peak,
                lh_1h=2,
                lh_4h=1,
                oi_drop=True,
                ema_depth=2,
            ),
            4,
        )


if __name__ == "__main__":
    unittest.main()
