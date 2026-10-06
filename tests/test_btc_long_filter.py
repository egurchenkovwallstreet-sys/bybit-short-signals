"""Фильтр лонга на перегреве (тест стратегии)."""

from __future__ import annotations

import unittest

from strategy_test.engine import BtcStrategyEngine
from strategy_test.swing_points import pivot_highs, price_near_pivot_high


def _bar(t: int, o: float, h: float, l: float, c: float, v: float = 1.0) -> dict:
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


class BtcLongFilterTest(unittest.TestCase):
    def test_blocks_when_rsi15_overheated(self) -> None:
        eng = BtcStrategyEngine("TESTUSDT")
        base = 100.0
        rows = []
        ts = 1_700_000_000_000
        for i in range(40):
            c = base + i * 0.5
            rows.append(_bar(ts + i * 900_000, c, c + 1, c - 0.2, c + 0.8, 10.0))
        for i in range(40, 55):
            c = base + 40 * 0.5 + (i - 40) * 3.0
            rows.append(_bar(ts + i * 900_000, c, c + 5, c, c + 4, 50.0))
        eng.set_bars("15", rows)
        self.assertTrue(eng._long_chase_blocked())

    def test_pivot_high_and_near_price(self) -> None:
        bars = []
        ts = 1_700_000_000_000
        prices = [100, 101, 102, 105, 103, 102, 104, 108, 106, 105, 107, 110, 108, 107, 109]
        for i, c in enumerate(prices):
            bars.append({"t": ts + i * 900_000, "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 1})
        highs = pivot_highs(bars, wing=2)
        self.assertTrue(len(highs) >= 1)
        peak = highs[-1]["price"]
        self.assertTrue(price_near_pivot_high(bars, peak, wing=2, tolerance_pct=0.5))


if __name__ == "__main__":
    unittest.main()
