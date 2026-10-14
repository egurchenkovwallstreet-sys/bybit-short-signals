"""Cursor SS: быстрый памп, вход на дампе, стоп −15% ROE, BE с +10%."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import config
from signal_engine.paper.css_detect import evaluate_css, find_css_pump
from signal_engine.paper.position import Position, css_trail_stop, net_breakeven_stop_price, net_roe_stop_price
from signal_engine.paper.store import PaperStore
from signal_engine.paper.strategy import PaperStrategy
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState

MIN = 60_000
NOW = (1_800_000_000_000 // 900_000) * 900_000


def css_state(*, dump: bool) -> SymbolState:
    """База 1.0, памп до 1.25 за 2 ч, 20 мин полка 1.22–1.24, опционально слив под полку."""
    state = SymbolState("CSSUSDT")
    first_1m = NOW - 400 * MIN
    rest_end = (first_1m // (15 * MIN)) * 15 * MIN
    state.bars_htf["15"] = [
        Bar(rest_end - (80 - i) * 15 * MIN, 1.0, 1.01, 0.99, 1.0, 20.0) for i in range(80)
    ]
    bars = []
    for i in range(400):
        ts = first_1m + i * MIN
        minutes_ago = (NOW - ts) // MIN
        if minutes_ago > 145:
            bars.append(Bar(ts, 1.0, 1.004, 0.996, 1.0, 8.0))
        elif minutes_ago > 25:
            frac = (145 - minutes_ago) / 120
            price = 1.0 + 0.25 * frac
            bars.append(Bar(ts, price, price + 0.003, price - 0.003, price, 160.0))
        elif minutes_ago == 25:
            bars.append(Bar(ts, 1.24, 1.25, 1.23, 1.24, 160.0))
        elif minutes_ago > 5:
            price = 1.23 + (0.01 if minutes_ago % 2 else -0.01)
            bars.append(Bar(ts, price, price, price, price, 12.0))
        elif dump:
            bars.append(Bar(ts, 1.18, 1.185, 1.175, 1.18, 40.0))
        else:
            price = 1.23
            bars.append(Bar(ts, price, price, price, price, 12.0))
    state.bars_1m = bars
    state.last_price = 1.18 if dump else 1.23
    state.turnover_24h_usdt = 3_000_000
    state.funding_rate = 0.0004
    return state


def css_tape(*, dump: bool) -> SymbolTape:
    tape = SymbolTape()
    for minutes_ago in range(179, -1, -1):
        ts = NOW - minutes_ago * MIN
        if minutes_ago > 25:
            tape.add_trade(ts, "Buy", 900.0)
            tape.add_trade(ts, "Sell", 200.0)
        elif dump and minutes_ago <= 5:
            tape.add_trade(ts, "Buy", 40.0)
            tape.add_trade(ts, "Sell", 120.0)
        else:
            tape.add_trade(ts, "Buy", 30.0)
            tape.add_trade(ts, "Sell", 70.0)
    tape.add_liquidation(NOW - 40 * MIN, "Sell", 8_000.0)
    tape.add_liquidation(NOW - 4 * MIN, "Buy", 500.0)
    return tape


class CssStopTest(unittest.TestCase):
    def test_stop_stays_minus_15_before_plus_10(self) -> None:
        stop = css_trail_stop(1.0, 0.995, 10, margin=50.0, entry_fee=0.0275)
        initial = net_roe_stop_price(1.0, 50.0, -15.0, 10, 0.0275, 0.0)
        self.assertAlmostEqual(stop, initial, places=6)

    def test_be_after_plus_10_roe(self) -> None:
        # +10% ROE при ×10 = цена 0.99
        be = net_breakeven_stop_price(1.0, 50.0, 10, 0.0275, 0.0)
        stop = css_trail_stop(1.0, 0.99, 10, margin=50.0, entry_fee=0.0275)
        self.assertAlmostEqual(stop, be, places=6)
        self.assertLess(stop, initial_if := net_roe_stop_price(1.0, 50.0, -15.0, 10, 0.0275, 0.0))
        self.assertGreater(stop, 0.99)

    def test_position_does_not_arm_be_at_small_green(self) -> None:
        pos = Position("X", 0, 1.0, 50.0, stop_style="css")
        self.assertIsNone(pos.update(0.999, 1.0, 0.999))
        self.assertLess(pos.max_roe(), 10.0)
        initial = net_roe_stop_price(1.0, 50.0, -15.0, 10, pos.entry_fee, 0.0)
        self.assertAlmostEqual(pos.stop_price, initial, places=5)

    def test_position_moves_to_be_at_ten_roe(self) -> None:
        pos = Position("X", 0, 1.0, 50.0, stop_style="css")
        self.assertIsNone(pos.update(0.99, 1.0, 0.99))
        self.assertGreaterEqual(pos.max_roe(), 10.0)
        be = net_breakeven_stop_price(1.0, 50.0, 10, pos.entry_fee, 0.0)
        self.assertAlmostEqual(pos.stop_price, be, places=5)


class CssDetectTest(unittest.TestCase):
    def test_finds_fast_pump_not_on_dump_yet(self) -> None:
        pump = find_css_pump(css_state(dump=False), css_tape(dump=False), NOW)
        self.assertIsNotNone(pump)
        assert pump is not None
        self.assertGreaterEqual(pump.growth_pct, 20.0)
        self.assertEqual(pump.to_data()["trigger"], "fast")
        ev = evaluate_css(css_state(dump=False), css_tape(dump=False), pump, {}, NOW)
        self.assertFalse(ev.checks["dump_break"]["ok"])
        self.assertFalse(ev.passed)

    def test_missing_tape_does_not_block_buys(self) -> None:
        state = css_state(dump=True)
        pump = find_css_pump(state, None, NOW)
        self.assertIsNotNone(pump)
        assert pump is not None
        self.assertIsNone(pump.buy_share_pct)
        ev = evaluate_css(state, SymbolTape(), pump, {}, NOW)
        self.assertTrue(ev.checks["pump_buys"]["ok"])

    def test_dump_enables_entry(self) -> None:
        state = css_state(dump=True)
        tape = css_tape(dump=True)
        pump = find_css_pump(state, tape, NOW)
        self.assertIsNotNone(pump)
        assert pump is not None
        ev = evaluate_css(state, tape, pump, {}, NOW)
        self.assertTrue(ev.checks["dump_break"]["ok"], ev.checks["dump_break"])
        self.assertTrue(ev.passed, ev.failed)


class CssStrategyTest(unittest.TestCase):
    def test_removed_from_the_board(self) -> None:
        self.assertNotIn("css", config.PAPER_VARIANTS)
        with tempfile.TemporaryDirectory() as tmp:
            strategy = PaperStrategy(PaperStore(Path(tmp) / "paper.db"))
            strategy.open()
            dumped = css_state(dump=True)
            strategy.tape.symbols[dumped.symbol] = css_tape(dump=True)
            view = strategy.scan({dumped.symbol: dumped}, NOW)["data"]
            self.assertNotIn("css", view["variants"])
            self.assertFalse(any(c.get("episode") == "css" for c in view["candidates"]))
            self.assertFalse(any(t["variant"] == "css" for t in view["open_trades"]))
            strategy.close()


if __name__ == "__main__":
    unittest.main()
