"""История пампа за 7 дней."""

from __future__ import annotations

import unittest

from signal_engine.pump_history import history_pump_metrics
from signal_engine.state import Bar, SymbolState


def _bar(ts: int, low: float, high: float) -> Bar:
    return Bar(ts, low, high, low, (low + high) / 2, 1.0, from_kline=True)


class PumpHistoryTests(unittest.TestCase):
    def test_peak_mult_after_retrace(self) -> None:
        state = SymbolState("PUMPUSDT")
        now = 3_000_000_000_000
        bars = []
        ts = now - 120 * 3_600_000
        for i in range(120):
            if i < 40:
                low, high = 10.0, 11.0
            elif i < 60:
                low, high = 10.0, 25.0
            else:
                low, high = 14.0, 16.0
            bars.append(_bar(ts, low, high))
            ts += 3_600_000
        state.bars_htf["60"] = bars
        state.last_price = 15.0
        hist = history_pump_metrics(state, now)
        self.assertIsNotNone(hist)
        assert hist is not None
        self.assertGreaterEqual(hist.peak_mult, 2.0)
        self.assertLess(hist.current_mult, hist.peak_mult)


if __name__ == "__main__":
    unittest.main()
