# -*- coding: utf-8 -*-
import unittest

import config
from signal_engine.paper.position import Position, liquidation_price, net_roe_stop_price, pyl_trail_stop
from signal_engine.paper.pyl_detect import PYL_MANDATORY, evaluate_pyl
from signal_engine.state import Bar, SymbolState

MIN = 60_000
STEP = 15 * MIN


class PylEntryTest(unittest.TestCase):
    def test_lower_high_confirm_on_third_bar(self) -> None:
        t0 = 1_800_000_000_000
        highs = [10, 11, 12, 20, 14, 13, 15, 14, 13, 12.0]
        lows = [9, 10, 11, 19, 13, 12, 13, 13, 12, 11.5]
        closes = [9.5, 11, 12, 19, 13.5, 12.5, 14, 13.5, 12.5, 12.0]
        bars = [
            Bar(t0 + i * STEP, closes[i] - 0.5, highs[i], lows[i], closes[i], 100.0)
            for i in range(len(highs))
        ]
        state = SymbolState("VACUUMUSDT", bars_htf={"15": bars}, last_price=12.0)
        now_ms = bars[-1].timestamp + STEP
        view = evaluate_pyl(state, now_ms)
        self.assertTrue(view["passed"], view["failed"])
        self.assertIn(config.PAPER_PYL_VARIANT, view["variants"])
        self.assertEqual(view["passed_count"], len(PYL_MANDATORY))

    def test_first_bar_after_vertex_does_not_enter(self) -> None:
        t0 = 1_800_000_000_000
        highs = [10, 11, 12, 20, 14, 13, 15, 14]
        lows = [9, 10, 11, 19, 13, 12, 13, 13]
        closes = [9.5, 11, 12, 19, 13.5, 12.5, 14, 13.0]
        bars = [
            Bar(t0 + i * STEP, closes[i] - 0.5, highs[i], lows[i], closes[i], 100.0)
            for i in range(len(highs))
        ]
        state = SymbolState("X", bars_htf={"15": bars}, last_price=13.0)
        now_ms = bars[-1].timestamp + STEP
        view = evaluate_pyl(state, now_ms)
        self.assertFalse(view["passed"])


class PylStopTest(unittest.TestCase):
    def test_initial_stop_minus_10_roe(self) -> None:
        pos = Position(
            symbol="X",
            opened_at=0,
            entry_price=1.0,
            margin=50.0,
            side="short",
            stop_style="pyl",
        )
        want = net_roe_stop_price(1.0, 50.0, -10.0, 10, pos.entry_fee, 0.0)
        self.assertAlmostEqual(pos.stop_price, min(want, pos.liq_price), places=6)
        self.assertLess(pos.stop_price, liquidation_price(1.0, 10))
        pos.best_price = 0.97
        pos._sync_stop(0.97)
        self.assertAlmostEqual(
            pos.stop_price,
            min(
                pos.liq_price,
                pyl_trail_stop(1.0, 0.97, 10, margin=50.0, entry_fee=pos.entry_fee),
            ),
            places=6,
        )


if __name__ == "__main__":
    unittest.main()
