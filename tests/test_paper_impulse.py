"""Импульс 5 и 15: объём ×3, направление свечи, агрессия >60%, выход как Трейл 20."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import config
from signal_engine.paper.impulse_detect import evaluate_impulse
from signal_engine.paper.position import Position, long_liquidation_price, price_for_long_roe, trail_stop
from signal_engine.paper.store import PaperStore
from signal_engine.paper.strategy import PaperStrategy
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState

MIN = 60_000


def _state(minutes: int, prev_vol: float, last_vol: float, *, up: bool, flat: bool = False) -> tuple[SymbolState, int, int]:
    step = minutes * MIN
    start = (1_700_000_000_000 // step) * step
    now = start + step + 1_000
    prev_ts = start - step
    last_ts = start
    bars: list[Bar] = []
    for bucket, vol in ((prev_ts, prev_vol), (last_ts, last_vol)):
        for i in range(minutes):
            ts = bucket + i * MIN
            if bucket == last_ts and not flat:
                if up:
                    bars.append(Bar(ts, 1.0 + i * 0.001, 1.02, 0.99, 1.01 + i * 0.001, vol / minutes))
                else:
                    bars.append(Bar(ts, 1.02 - i * 0.001, 1.03, 0.99, 1.00 - i * 0.001, vol / minutes))
            else:
                bars.append(Bar(ts, 1.0, 1.01, 0.99, 1.0, vol / minutes))
    state = SymbolState(symbol="XUSDT", bars_1m=bars, last_price=bars[-1].close)
    return state, now, last_ts


def _tape(start_ms: int, minutes: int, buy: float, sell: float) -> SymbolTape:
    tape = SymbolTape()
    for i in range(minutes):
        ts = start_ms + i * MIN + 1_000
        if buy:
            tape.add_trade(ts, "Buy", buy / minutes)
        if sell:
            tape.add_trade(ts, "Sell", sell / minutes)
    return tape


class ImpulseEntryTest(unittest.TestCase):
    def test_long_when_volume_and_buys_clear_the_bar(self) -> None:
        state, now, last_ts = _state(5, 10.0, 31.0, up=True)
        ev = evaluate_impulse(state, _tape(last_ts, 5, 80.0, 20.0), now, 5)
        self.assertTrue(ev.passed)
        self.assertEqual(ev.side, "long")
        self.assertEqual(ev.to_data()["variants"], ["i5"])

    def test_short_on_red_bar_with_sells(self) -> None:
        state, now, last_ts = _state(15, 10.0, 40.0, up=False)
        ev = evaluate_impulse(state, _tape(last_ts, 15, 20.0, 80.0), now, 15)
        self.assertTrue(ev.passed)
        self.assertEqual(ev.side, "short")
        self.assertEqual(ev.to_data()["variants"], ["i15"])

    def test_exact_triple_volume_does_not_enter(self) -> None:
        state, now, last_ts = _state(5, 10.0, 30.0, up=True)
        ev = evaluate_impulse(state, _tape(last_ts, 5, 90.0, 10.0), now, 5)
        self.assertFalse(ev.passed)
        self.assertIn("volume_x3", ev.failed)

    def test_flat_close_and_thin_flow_fail(self) -> None:
        state, now, last_ts = _state(5, 10.0, 40.0, up=True, flat=True)
        ev = evaluate_impulse(state, _tape(last_ts, 5, 60.0, 40.0), now, 5)
        self.assertFalse(ev.passed)
        self.assertIn("price_side", ev.failed)
        self.assertIn("flow_side", ev.failed)

    def test_missing_tape_fails(self) -> None:
        state, now, _last = _state(5, 10.0, 40.0, up=True)
        ev = evaluate_impulse(state, None, now, 5)
        self.assertIn("flow_side", ev.failed)


class ImpulseStopTest(unittest.TestCase):
    def test_short_matches_trail_20(self) -> None:
        common = dict(symbol="X", opened_at=0, entry_price=1.0, margin=50.0, side="short")
        trail = Position(**common, stop_style="default")
        impulse = Position(**common, stop_style="impulse")
        trail.best_price = impulse.best_price = 0.97
        trail._sync_stop(0.97)
        impulse._sync_stop(0.97)
        self.assertAlmostEqual(impulse.stop_price, trail.stop_price, places=6)
        self.assertAlmostEqual(
            impulse.stop_price,
            trail_stop(1.0, 0.97, 10, 0.0, margin=50.0, entry_fee=impulse.entry_fee),
            places=6,
        )

    def test_long_uses_same_roe_ladder_not_the_long_t20_stop(self) -> None:
        impulse = Position(symbol="X", opened_at=0, entry_price=1.0, margin=50.0, side="long", stop_style="impulse")
        classic = Position(symbol="X", opened_at=0, entry_price=1.0, margin=50.0, side="long", stop_style="default")
        self.assertAlmostEqual(impulse.stop_price, long_liquidation_price(1.0, 10), places=6)
        self.assertGreater(classic.stop_price, impulse.stop_price)
        impulse.best_price = 1.01
        impulse._sync_stop(1.01)
        self.assertAlmostEqual(impulse.stop_price, price_for_long_roe(1.0, 5.0, 10), places=6)
        impulse.best_price = 1.03
        impulse._sync_stop(1.03)
        self.assertAlmostEqual(impulse.stop_price, price_for_long_roe(1.0, 10.0, 10), places=6)


class ImpulseOpenTest(unittest.TestCase):
    def test_opens_impulse_5_long_once_per_bar(self) -> None:
        state, now, last_ts = _state(5, 10.0, 40.0, up=True)
        tape = _tape(last_ts, 5, 80.0, 10.0)
        with tempfile.TemporaryDirectory() as tmp:
            strategy = PaperStrategy(PaperStore(Path(tmp) / "paper.db"))
            strategy.open()
            strategy.balances["i5"] = 1000.0
            strategy.tape.symbols["XUSDT"] = tape
            strategy._evaluate_impulse({"XUSDT": state}, now)
            trade = strategy.trades[("i5", "XUSDT")]
            self.assertEqual(trade.pos.side, "long")
            self.assertEqual(trade.pos.stop_style, "impulse")
            self.assertEqual(config.paper_stop_style("i5"), "impulse")
            self.assertEqual(config.paper_peak_gap_roe("i5"), 0.0)
            strategy._evaluate_impulse({"XUSDT": state}, now)
            self.assertEqual(len([t for t in strategy.trades.values() if t.variant == "i5"]), 1)
            strategy.close()
