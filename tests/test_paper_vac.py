# -*- coding: utf-8 -*-
import unittest

import config
from signal_engine.paper.vac_detect import VAC_MANDATORY, _bearish, evaluate_vac
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import pivot_highs_indexed

MIN = 60_000
STEP = 5 * MIN


def _acb_bars(*, bearish_after_b: bool) -> list[Bar]:
    """A@2 (11), C@7 (low 8.5), B@12 (high 9.5), confirm@13."""
    t0 = 1_800_000_000_000
    n = 14
    highs = [
        10.0,
        10.2,
        11.0,
        10.4,
        10.0,
        9.6,
        9.2,
        9.0,
        8.8,
        9.1,
        9.3,
        9.4,
        9.5,
        9.2,
    ]
    lows = [h - 0.5 for h in highs]
    lows[8] = 8.0
    opens = [highs[i] - 0.15 for i in range(n)]
    closes = [highs[i] - 0.25 for i in range(n)]
    bi = 12
    opens[bi] = 9.55
    closes[bi] = 9.25
    if bearish_after_b:
        opens[bi + 1] = 9.15
        closes[bi + 1] = 8.85
    else:
        opens[bi + 1] = 8.9
        closes[bi + 1] = 9.05
    return [Bar(t0 + i * STEP, opens[i], highs[i], lows[i], closes[i], 100.0) for i in range(n)]


class VacSimpleEntryTest(unittest.TestCase):
    def test_two_bearish_after_b_peak(self) -> None:
        bars = _acb_bars(bearish_after_b=True)
        closed = bars
        highs = pivot_highs_indexed(closed, 1)
        self.assertTrue(any(p["bar_index"] == 2 for p in highs))
        self.assertTrue(any(p["bar_index"] == 12 for p in highs))
        state = SymbolState("X", bars_htf={"5": bars}, last_price=bars[-1].close)
        now_ms = bars[-1].timestamp + STEP
        view = evaluate_vac(state, now_ms)
        self.assertTrue(view["passed"], view["failed"])
        self.assertIn(config.PAPER_VAC_VARIANT, view["variants"])
        self.assertEqual(view["passed_count"], len(VAC_MANDATORY))

    def test_no_entry_if_second_after_b_bullish(self) -> None:
        bars = _acb_bars(bearish_after_b=False)
        state = SymbolState("X", bars_htf={"5": bars}, last_price=bars[-1].close)
        now_ms = bars[-1].timestamp + STEP
        view = evaluate_vac(state, now_ms)
        self.assertFalse(view["passed"])


class VacTriggerTest(unittest.TestCase):
    def test_bearish(self) -> None:
        self.assertTrue(_bearish(Bar(0, 10.0, 10.5, 9.5, 9.8, 1.0)))
        self.assertFalse(_bearish(Bar(0, 9.8, 10.5, 9.5, 10.0, 1.0)))


if __name__ == "__main__":
    unittest.main()
