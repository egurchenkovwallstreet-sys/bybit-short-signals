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
    def test_entry_below_first_bearish_close(self) -> None:
        t0 = 1_800_000_000_000
        highs = [10, 11, 12, 20, 14, 13, 15, 14, 13, 12.5]
        lows = [9, 10, 11, 19, 13, 12, 13, 13, 12, 11.5]
        closes = [9.5, 11, 12, 19, 13.5, 12.5, 14, 13.0, 12.0, 11.8]
        opens = [10.0, 11.5, 12.5, 19.5, 14.0, 13.0, 14.5, 13.8, 12.6, 12.4]
        bars = [
            Bar(t0 + i * STEP, opens[i], highs[i], lows[i], closes[i], 100.0)
            for i in range(len(highs))
        ]
        state = SymbolState("VACUUMUSDT", bars_htf={"15": bars}, last_price=11.8)
        now_ms = bars[-1].timestamp + STEP
        view = evaluate_pyl(state, now_ms)
        self.assertTrue(view["passed"], view["failed"])
        self.assertIn(config.PAPER_PYL_VARIANT, view["variants"])
        self.assertEqual(view["passed_count"], len(PYL_MANDATORY))

    def test_no_entry_when_first_after_high_is_bullish(self) -> None:
        t0 = 1_800_000_000_000
        highs = [10, 11, 12, 20, 14, 13, 15, 14, 13, 12.5]
        lows = [9, 10, 11, 19, 13, 12, 13, 13, 12, 11.5]
        closes = [9.5, 11, 12, 19, 13.5, 12.5, 14, 13.2, 12.4, 11.8]
        opens = [10.0, 11.5, 12.5, 19.5, 14.0, 13.0, 14.5, 13.0, 12.0, 12.4]
        bars = [
            Bar(t0 + i * STEP, opens[i], highs[i], lows[i], closes[i], 100.0)
            for i in range(len(highs))
        ]
        state = SymbolState("X", bars_htf={"15": bars}, last_price=11.8)
        now_ms = bars[-1].timestamp + STEP
        view = evaluate_pyl(state, now_ms)
        self.assertFalse(view["passed"])

    def test_no_entry_when_close_not_below_bear1(self) -> None:
        t0 = 1_800_000_000_000
        highs = [10, 11, 12, 20, 14, 13, 15, 14, 13, 12.5]
        lows = [9, 10, 11, 19, 13, 12, 13, 13, 12, 11.5]
        closes = [9.5, 11, 12, 19, 13.5, 12.5, 14, 13.0, 12.0, 13.2]
        opens = [10.0, 11.5, 12.5, 19.5, 14.0, 13.0, 14.5, 13.8, 12.6, 12.8]
        bars = [
            Bar(t0 + i * STEP, opens[i], highs[i], lows[i], closes[i], 100.0)
            for i in range(len(highs))
        ]
        state = SymbolState("X", bars_htf={"15": bars}, last_price=13.2)
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
