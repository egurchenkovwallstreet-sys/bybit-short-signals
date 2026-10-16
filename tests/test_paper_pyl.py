# -*- coding: utf-8 -*-
import unittest

import config
from signal_engine.paper.position import (
    Position,
    liquidation_price,
    net_roe_stop_price,
    price_for_roe,
    pyl_trail_stop,
    roe_pct,
)
from signal_engine.paper.pyl_detect import PYL_MANDATORY, evaluate_pyl
from signal_engine.state import Bar, SymbolState

MIN = 60_000
STEP = 15 * MIN


class PylEntryTest(unittest.TestCase):
    def test_lower_high_confirm_on_third_bar(self) -> None:
        t0 = 1_800_000_000_000
        highs = [8, 9, 10, 11, 20, 12, 11, 13, 14, 13, 12.0]
        lows = [7, 8, 9, 10, 19, 11, 10, 12, 13, 12, 11.5]
        closes = [7.5, 9, 10, 11, 19, 11.5, 10.5, 12.5, 13.5, 13.0, 13.4]
        bars = [
            Bar(t0 + i * STEP, closes[i] - 0.5, highs[i], lows[i], closes[i], 100.0)
            for i in range(len(highs))
        ]
        state = SymbolState("VACUUMUSDT", bars_htf={"15": bars}, last_price=13.4)
        now_ms = bars[-1].timestamp + STEP
        view = evaluate_pyl(state, now_ms)
        self.assertTrue(view["passed"], view["failed"])
        self.assertIn(config.PAPER_PYL_VARIANT, view["variants"])
        self.assertEqual(view["passed_count"], len(PYL_MANDATORY))
        self.assertEqual(view["metrics"]["offset_bars"], 2)

    def test_no_entry_when_close_not_below_vertex(self) -> None:
        t0 = 1_800_000_000_000
        highs = [8, 9, 10, 11, 20, 12, 11, 13, 14, 14]
        lows = [7, 8, 9, 10, 19, 11, 10, 12, 13, 13]
        closes = [7.5, 9, 10, 11, 19, 11.5, 10.5, 12.5, 13.5, 14.0]
        bars = [
            Bar(t0 + i * STEP, closes[i] - 0.5, highs[i], lows[i], closes[i], 100.0)
            for i in range(len(highs))
        ]
        state = SymbolState("X", bars_htf={"15": bars}, last_price=14.0)
        now_ms = bars[-1].timestamp + STEP
        view = evaluate_pyl(state, now_ms)
        self.assertFalse(view["passed"])

    def test_rejects_micro_bounce_at_bottom(self) -> None:
        """Отскок у дна: V₂ не max high после V₁ — входа нет."""
        t0 = 1_800_000_000_000
        highs = [8, 9, 10, 11, 20, 12, 11, 13, 14, 13, 12, 11, 10.5, 10.2, 10.0, 10.3, 10.1]
        lows = [7] * len(highs)
        closes = [h - 0.3 for h in highs]
        bars = [
            Bar(t0 + i * STEP, c - 0.2, highs[i], lows[i], closes[i], 100.0)
            for i, c in enumerate(closes)
        ]
        state = SymbolState("X", bars_htf={"15": bars}, last_price=closes[-1])
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

    def test_trail_5pp_from_peak_at_10_roe(self) -> None:
        entry = 1.0
        lev = 10
        margin = 50.0
        pos = Position(symbol="X", opened_at=0, entry_price=entry, margin=margin, side="short", stop_style="pyl")
        pos.best_price = price_for_roe(entry, 12.0, lev)
        pos._sync_stop(pos.best_price)
        want = min(
            pos.liq_price,
            pyl_trail_stop(entry, pos.best_price, lev, margin=margin, entry_fee=pos.entry_fee),
        )
        self.assertAlmostEqual(pos.stop_price, want, places=6)
        self.assertGreaterEqual(roe_pct(entry, pos.stop_price, lev), 7.0)


if __name__ == "__main__":
    unittest.main()
