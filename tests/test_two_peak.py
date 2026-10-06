"""Две вершины: LH / double top, ≥5 свечей между."""

from __future__ import annotations

import unittest

import config
from signal_engine.state import Bar
from signal_engine.swing_highs import find_two_peak_match


def _bar(i: int, high: float, ts_base: int = 1_000_000_000_000) -> Bar:
    t = ts_base + i * 3_600_000
    low = high * 0.95
    return Bar(t, low, high, low, (low + high) / 2, 1.0, from_kline=True)


class TwoPeakTests(unittest.TestCase):
    def test_lower_high_with_gap(self) -> None:
        bars: list[Bar] = []
        highs = [10.0] * 8 + [20.0] + [12.0] * 6 + [15.0] + [11.0] * 10
        for i, h in enumerate(highs):
            bars.append(_bar(i, h))
        now = bars[-1].timestamp + 3_600_000
        match = find_two_peak_match(bars, bars[0].timestamp, "60", now, wing=2)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertIn(match.kind, ("lower_high", "double_top"))
        self.assertGreaterEqual(match.bars_between, config.X2_RETRACE_MIN_BARS_BETWEEN_PEAKS)

    def test_marginal_higher_second_allowed(self) -> None:
        from signal_engine.swing_highs import _peak_pair_kind

        self.assertEqual(_peak_pair_kind(100.0, 108.0), "marginal_hh")
        self.assertIsNone(_peak_pair_kind(100.0, 120.0))

    def test_second_higher_rejected(self) -> None:
        bars: list[Bar] = []
        for i in range(30):
            h = 10.0 if i < 10 else (25.0 if i == 20 else 12.0)
            bars.append(_bar(i, h))
        now = bars[-1].timestamp + 3_600_000
        match = find_two_peak_match(bars, bars[0].timestamp, "60", now, wing=2)
        if match is not None and match.second_price > match.first_price * 1.02:
            self.fail("second peak should not exceed first")


if __name__ == "__main__":
    unittest.main()
