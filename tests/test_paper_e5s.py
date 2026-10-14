"""EMA50 5м шорт: тот же памп, вход на закрытии 5м под EMA50, стоп −20% ROE."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import config
from signal_engine.paper.detect import find_pump
from signal_engine.paper.e5s_detect import evaluate_e5s
from signal_engine.paper.position import Position, e5s_trail_stop, net_breakeven_stop_price, net_roe_stop_price
from signal_engine.paper.store import PaperStore
from signal_engine.paper.strategy import PaperStrategy
from signal_engine.state import Bar
from tests.test_paper_strategy import NOW, MIN, pumped_state, pumped_tape

STEP = 5 * MIN


def _five_min_history(*, last_close: float) -> list[Bar]:
    """60 закрытых 5м: база 1.0, последняя закрывается last_close."""
    last_ts = NOW - STEP
    bars = []
    for i in range(60):
        ts = last_ts - (59 - i) * STEP
        if i < 59:
            bars.append(Bar(ts, 1.0, 1.01, 0.99, 1.0, 40.0))
        else:
            hi = max(1.01, last_close)
            bars.append(Bar(ts, 1.0, hi, min(0.99, last_close), last_close, 80.0))
    return bars


def _dump_last_closed_5m(state, price: float = 1.10) -> None:
    for bar in state.bars_1m:
        if NOW - STEP <= bar.timestamp < NOW:
            bar.open = price
            bar.high = price + 0.004
            bar.low = price - 0.004
            bar.close = price
    state.last_price = price


class E5sStopTest(unittest.TestCase):
    def test_stop_stays_minus_20_before_plus_10(self) -> None:
        stop = e5s_trail_stop(1.0, 0.995, 10, margin=50.0, entry_fee=0.0275)
        initial = net_roe_stop_price(1.0, 50.0, -20.0, 10, 0.0275, 0.0)
        self.assertAlmostEqual(stop, initial, places=6)

    def test_be_after_plus_10_roe(self) -> None:
        be = net_breakeven_stop_price(1.0, 50.0, 10, 0.0275, 0.0)
        stop = e5s_trail_stop(1.0, 0.99, 10, margin=50.0, entry_fee=0.0275)
        self.assertAlmostEqual(stop, be, places=6)

    def test_position_keeps_minus_20_until_ten(self) -> None:
        pos = Position("X", 0, 1.0, 50.0, stop_style="e5s")
        self.assertIsNone(pos.update(0.999, 1.0, 0.999))
        initial = net_roe_stop_price(1.0, 50.0, -20.0, 10, pos.entry_fee, 0.0)
        self.assertAlmostEqual(pos.stop_price, initial, places=5)
        self.assertIsNone(pos.update(0.99, 1.0, 0.99))
        be = net_breakeven_stop_price(1.0, 50.0, 10, pos.entry_fee, 0.0)
        self.assertAlmostEqual(pos.stop_price, be, places=5)


class E5sDetectTest(unittest.TestCase):
    def test_break_and_confirms_pass(self) -> None:
        state = pumped_state("E5SUSDT")
        _dump_last_closed_5m(state, 1.10)
        tape = pumped_tape()
        pump = find_pump(state, tape, NOW)
        self.assertIsNotNone(pump)
        assert pump is not None
        klines = {"5": _five_min_history(last_close=1.10)}
        ev = evaluate_e5s(state, tape, pump, klines, NOW)
        self.assertTrue(ev.checks["peak_age"]["ok"], ev.checks["peak_age"])
        self.assertTrue(ev.checks["sells_5_15"]["ok"], ev.checks["sells_5_15"])
        self.assertTrue(ev.checks["short_liq_faded"]["ok"], ev.checks["short_liq_faded"])
        self.assertTrue(ev.checks["ema50_5m_break"]["ok"], ev.checks["ema50_5m_break"])
        self.assertTrue(ev.passed, ev.failed)

    def test_no_break_no_entry(self) -> None:
        state = pumped_state("E5SUSDT")
        tape = pumped_tape()
        pump = find_pump(state, tape, NOW)
        self.assertIsNotNone(pump)
        assert pump is not None
        ev = evaluate_e5s(state, tape, pump, {"5": _five_min_history(last_close=1.35)}, NOW)
        self.assertFalse(ev.checks["ema50_5m_break"]["ok"])
        self.assertFalse(ev.passed)


class E5sStrategyTest(unittest.TestCase):
    def test_opens_on_5m_close_below_ema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strategy = PaperStrategy(PaperStore(Path(tmp) / "paper.db"))
            strategy.open()
            state = pumped_state("E5SUSDT")
            _dump_last_closed_5m(state, 1.10)
            strategy.tape.symbols[state.symbol] = pumped_tape()
            strategy.klines[state.symbol] = {"5": _five_min_history(last_close=1.10)}
            view = strategy.scan({state.symbol: state}, NOW)["data"]
            e5s = [t for t in view["open_trades"] if t["variant"] == "e5s"]
            self.assertEqual(len(e5s), 1, view["open_trades"])
            pos = strategy.trades[("e5s", state.symbol)].pos
            self.assertEqual(pos.stop_style, "e5s")
            initial = net_roe_stop_price(
                pos.entry_price, pos.margin, config.PAPER_E5S_INITIAL_STOP_ROE, pos.leverage, pos.entry_fee, 0.0
            )
            self.assertAlmostEqual(pos.stop_price, initial, places=5)
            strategy.close()

    def test_does_not_open_without_ema_break(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strategy = PaperStrategy(PaperStore(Path(tmp) / "paper.db"))
            strategy.open()
            state = pumped_state("E5SUSDT")
            strategy.tape.symbols[state.symbol] = pumped_tape()
            strategy.klines[state.symbol] = {"5": _five_min_history(last_close=1.35)}
            view = strategy.scan({state.symbol: state}, NOW)["data"]
            self.assertFalse(any(t["variant"] == "e5s" for t in view["open_trades"]))
            strategy.close()


if __name__ == "__main__":
    unittest.main()
