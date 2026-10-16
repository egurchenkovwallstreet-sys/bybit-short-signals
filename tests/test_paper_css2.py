"""Курсор СС 2: быстрый памп, откат 5–8%, стоп −60% ROE, половина на −15% от пика."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import config
from signal_engine.paper.css2_detect import evaluate_css2, find_css2_pump
from signal_engine.paper.position import Position, css2_trail_stop, net_roe_stop_price, price_for_roe
from signal_engine.paper.store import PaperStore
from signal_engine.paper.strategy import PaperStrategy
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState

MIN = 60_000
NOW = (1_800_000_000_000 // 900_000) * 900_000
PEAK = 1.50
ENTRY = PEAK * 0.935  # откат 6.5%


def css2_state(*, dd: float = 6.5) -> SymbolState:
    state = SymbolState("CSS2USDT")
    last = PEAK * (1.0 - dd / 100.0)
    bars: list[Bar] = []
    for i in range(600):
        ts = NOW - (599 - i) * MIN
        minutes_ago = (NOW - ts) // MIN
        if minutes_ago > 180:
            bars.append(Bar(ts, 1.08, 1.09, 1.07, 1.08, 10.0))
        elif minutes_ago > 30:
            frac = (180 - minutes_ago) / 150
            price = 1.0 + (PEAK - 1.0) * frac
            bars.append(Bar(ts, price, price + 0.002, max(price - 0.01, 1.0), price, 40.0))
        elif minutes_ago == 30:
            bars.append(Bar(ts, PEAK - 0.02, PEAK, PEAK - 0.03, PEAK - 0.01, 80.0))
        elif minutes_ago >= 15:
            bars.append(Bar(ts, 1.46, 1.47, 1.44, 1.45, 20.0))
        else:
            bars.append(Bar(ts, last, last + 0.002, last - 0.002, last, 15.0))
    state.bars_1m = bars
    state.last_price = last
    state.turnover_24h_usdt = 2_000_000
    state.oi_5m = [(NOW - 80 * MIN, 1000.0), (NOW, 1000.0)]
    state.book_bids = {round(last * 0.995, 4): 10.0}
    state.book_asks = {round(last * 1.005, 4): 40.0}
    return state


def btc_state() -> SymbolState:
    state = SymbolState(config.PAPER_BTC_SYMBOL)
    state.bars_1m = [
        Bar(NOW - (599 - i) * MIN, 100.0, 100.1, 99.9, 100.0, 5.0) for i in range(600)
    ]
    state.last_price = 100.0
    state.turnover_24h_usdt = 50_000_000
    return state


def css2_tape() -> SymbolTape:
    tape = SymbolTape()
    for minutes_ago in range(20, -1, -1):
        ts = NOW - minutes_ago * MIN
        tape.add_trade(ts, "Buy", 20.0)
        tape.add_trade(ts, "Sell", 80.0)
    tape.add_liquidation(NOW - 30 * MIN, "Sell", 10_000.0)
    return tape


class Css2StopTest(unittest.TestCase):
    def test_initial_stop_is_minus_60_roe(self) -> None:
        stop = css2_trail_stop(1.0, 0.99, 10, margin=50.0, entry_fee=0.0275)
        initial = net_roe_stop_price(1.0, 50.0, -60.0, 10, 0.0275, 0.0)
        self.assertAlmostEqual(stop, initial, places=6)
        self.assertLess(stop, 1.07)

    def test_breakeven_after_plus_50_roe(self) -> None:
        best = price_for_roe(1.0, 50.0, 10)
        stop = css2_trail_stop(1.0, best, 10, margin=50.0, entry_fee=0.0275)
        self.assertLess(stop, 1.0)
        self.assertGreater(stop, best)

    def test_half_locks_plus_50_roe(self) -> None:
        locked = price_for_roe(1.0, 50.0, 10)
        stop = css2_trail_stop(1.0, 0.99, 10, margin=50.0, entry_fee=0.0275, scaled_half=True)
        self.assertAlmostEqual(stop, locked, places=6)

    def test_realize_half_shrinks_margin(self) -> None:
        pos = Position("X", 0, 1.0, 50.0, stop_style="css2")
        before = pos.margin
        pnl = pos.realize_half(0.9)
        self.assertGreater(pnl, 0)
        self.assertAlmostEqual(pos.margin, before / 2, places=6)
        self.assertTrue(pos.scaled_half)
        self.assertEqual(pos.realize_half(0.8), 0.0)


class Css2DetectTest(unittest.TestCase):
    def test_entry_window_passes(self) -> None:
        state = css2_state()
        pump = find_css2_pump(state, NOW)
        self.assertIsNotNone(pump)
        assert pump is not None
        self.assertGreaterEqual(pump.growth_pct, 40.0)
        ev = evaluate_css2(state, css2_tape(), btc_state(), pump, {}, NOW)
        self.assertTrue(ev.passed, ev.failed)

    def test_shallow_pullback_fails(self) -> None:
        state = css2_state(dd=2.0)
        pump = find_css2_pump(state, NOW)
        self.assertIsNotNone(pump)
        assert pump is not None
        ev = evaluate_css2(state, css2_tape(), btc_state(), pump, {}, NOW)
        self.assertFalse(ev.checks["drawdown_band"]["ok"])
        self.assertFalse(ev.passed)


@unittest.skipUnless("css2" in config.PAPER_VARIANTS, "Курсор СС 2 снят с теста")
class Css2StrategyTest(unittest.TestCase):
    def test_opens_once_then_half_then_blocks_valley(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strategy = PaperStrategy(PaperStore(Path(tmp) / "paper.db"))
            strategy.open()
            state = css2_state()
            btc = btc_state()
            strategy.tape.symbols[state.symbol] = css2_tape()
            view = strategy.scan({state.symbol: state, btc.symbol: btc}, NOW)["data"]
            trades = [t for t in view["open_trades"] if t["variant"] == "css2"]
            self.assertEqual(len(trades), 1, view["candidates"])
            pos = strategy.trades[("css2", state.symbol)].pos
            self.assertEqual(pos.stop_style, "css2")
            self.assertFalse(pos.scaled_half)
            balance = strategy.balances["css2"]

            half = PEAK * 0.85
            state.bars_1m.append(Bar(NOW + MIN, half, half, half, half, 10.0))
            state.last_price = half
            strategy.scan({state.symbol: state, btc.symbol: btc}, NOW + MIN + 1000)
            pos = strategy.trades[("css2", state.symbol)].pos
            self.assertTrue(pos.scaled_half)
            self.assertGreater(strategy.balances["css2"], balance)
            self.assertEqual(len([t for t in strategy.trades if t[0] == "css2"]), 1)

            stop = pos.stop_price + 0.01
            state.bars_1m.append(Bar(NOW + 2 * MIN, stop, stop, half, stop, 10.0))
            state.last_price = stop
            strategy.scan({state.symbol: state, btc.symbol: btc}, NOW + 2 * MIN + 1000)
            self.assertNotIn(("css2", state.symbol), strategy.trades)

            again = css2_state()
            strategy.tape.symbols[again.symbol] = css2_tape()
            strategy.scan({again.symbol: again, btc.symbol: btc}, NOW + 3 * MIN)
            self.assertNotIn(("css2", again.symbol), strategy.trades)
            self.assertNotIn(again.symbol, strategy.css2_candidates)
            strategy.close()


if __name__ == "__main__":
    unittest.main()
