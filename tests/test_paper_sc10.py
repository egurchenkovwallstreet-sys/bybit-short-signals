"""Скальп 10: пробой 1м, трейл 10% ROE с входа, лонг и шорт."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import config
from signal_engine.paper.position import Position, net_roe_stop_price, net_roe_stop_price_long, sc10_trail_stop
from signal_engine.paper.sc10_detect import evaluate_sc10
from signal_engine.paper.store import PaperStore
from signal_engine.paper.strategy import PaperStrategy
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState

MIN = 60_000
NOW = (1_800_000_000_000 // 60_000) * 60_000 + 5_000


def _bars_flat_then_break(*, long: bool) -> list[Bar]:
    bars = []
    first = NOW - 40 * MIN
    first = (first // MIN) * MIN
    for i in range(35):
        ts = first + i * MIN
        bars.append(Bar(ts, 1.0, 1.004, 0.996, 1.0, 10.0))
    ts = first + 35 * MIN
    if long:
        bars.append(Bar(ts, 1.002, 1.03, 1.001, 1.028, 40.0))
    else:
        bars.append(Bar(ts, 0.998, 0.999, 0.97, 0.972, 40.0))
    return bars


def scalp_state(*, long: bool) -> SymbolState:
    state = SymbolState("SC10USDT")
    state.bars_1m = _bars_flat_then_break(long=long)
    state.last_price = 1.028 if long else 0.972
    state.oi_5m = [(NOW - (20 - i) * 5 * MIN, 1000.0 + i * 8) for i in range(21)]
    return state


def scalp_tape(*, long: bool, bar_ts: int | None = None) -> SymbolTape:
    tape = SymbolTape()
    close_ts = bar_ts if bar_ts is not None else ((NOW // MIN) * MIN) - MIN
    for minutes_ago in range(30, -1, -1):
        ts = close_ts + 1_000 - minutes_ago * MIN
        if minutes_ago <= 2:
            if long:
                tape.add_trade(ts, "Buy", 800.0)
                tape.add_trade(ts, "Sell", 100.0)
            else:
                tape.add_trade(ts, "Buy", 100.0)
                tape.add_trade(ts, "Sell", 800.0)
        else:
            tape.add_trade(ts, "Buy", 50.0)
            tape.add_trade(ts, "Sell", 50.0)
    return tape


def btc_flat() -> SymbolState:
    state = SymbolState(config.PAPER_BTC_SYMBOL)
    first = (NOW // MIN) * MIN - 20 * MIN
    state.bars_1m = [Bar(first + i * MIN, 100.0, 100.1, 99.9, 100.0, 10.0) for i in range(20)]
    state.last_price = 100.0
    return state


class Sc10StopTest(unittest.TestCase):
    def test_short_trail_from_minus_10(self) -> None:
        stop0 = sc10_trail_stop(1.0, 1.0, 10, margin=50.0, entry_fee=0.0275, side="short")
        init = net_roe_stop_price(1.0, 50.0, -10.0, 10, 0.0275, 0.0)
        self.assertAlmostEqual(stop0, init, places=6)
        stop5 = sc10_trail_stop(1.0, 0.995, 10, margin=50.0, entry_fee=0.0275, side="short")
        at5 = net_roe_stop_price(1.0, 50.0, -5.0, 10, 0.0275, 0.0)
        self.assertAlmostEqual(stop5, at5, places=6)
        stop10 = sc10_trail_stop(1.0, 0.99, 10, margin=50.0, entry_fee=0.0275, side="short")
        at0 = net_roe_stop_price(1.0, 50.0, 0.0, 10, 0.0275, 0.0)
        self.assertAlmostEqual(stop10, at0, places=6)

    def test_long_trail_from_minus_10(self) -> None:
        pos = Position("X", 0, 1.0, 50.0, side="long", stop_style="sc10")
        init = net_roe_stop_price_long(1.0, 50.0, -10.0, 10, pos.entry_fee, 0.0)
        self.assertAlmostEqual(pos.stop_price, init, places=5)
        self.assertIsNone(pos.update(1.0, 1.01, 1.01))
        at0 = net_roe_stop_price_long(1.0, 50.0, 0.0, 10, pos.entry_fee, 0.0)
        self.assertAlmostEqual(pos.stop_price, at0, places=5)


class Sc10DetectTest(unittest.TestCase):
    def test_long_break_passes(self) -> None:
        state = scalp_state(long=True)
        ev = evaluate_sc10(state, scalp_tape(long=True, bar_ts=state.bars_1m[-1].timestamp), btc_flat(), NOW)
        self.assertEqual(ev.side, "long")
        self.assertTrue(ev.passed, ev.failed)

    def test_short_break_passes(self) -> None:
        state = scalp_state(long=False)
        ev = evaluate_sc10(state, scalp_tape(long=False, bar_ts=state.bars_1m[-1].timestamp), btc_flat(), NOW)
        self.assertEqual(ev.side, "short")
        self.assertTrue(ev.passed, ev.failed)

    def test_no_break_no_entry(self) -> None:
        state = scalp_state(long=True)
        state.bars_1m[-1] = Bar(state.bars_1m[-1].timestamp, 1.0, 1.004, 0.996, 1.001, 40.0)
        state.last_price = 1.001
        ev = evaluate_sc10(state, scalp_tape(long=True, bar_ts=state.bars_1m[-1].timestamp), btc_flat(), NOW)
        self.assertFalse(ev.checks["range_break"]["ok"])
        self.assertFalse(ev.passed)

    def test_price_back_inside_range_blocks(self) -> None:
        state = scalp_state(long=True)
        state.last_price = 1.002
        ev = evaluate_sc10(state, scalp_tape(long=True, bar_ts=state.bars_1m[-1].timestamp), btc_flat(), NOW)
        self.assertTrue(ev.checks["range_break"]["ok"])
        self.assertFalse(ev.checks["follow_through"]["ok"])
        self.assertFalse(ev.passed)

    def test_oi_flat_blocks(self) -> None:
        state = scalp_state(long=True)
        state.oi_5m = [(NOW - (20 - i) * 5 * MIN, 1000.0) for i in range(21)]
        ev = evaluate_sc10(state, scalp_tape(long=True, bar_ts=state.bars_1m[-1].timestamp), btc_flat(), NOW)
        self.assertFalse(ev.checks["oi_ok"]["ok"])
        self.assertFalse(ev.passed)


class Sc10StrategyTest(unittest.TestCase):
    def test_opens_long(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strategy = PaperStrategy(PaperStore(Path(tmp) / "paper.db"))
            strategy.open()
            state = scalp_state(long=True)
            btc = btc_flat()
            strategy.tape.symbols[state.symbol] = scalp_tape(long=True, bar_ts=state.bars_1m[-1].timestamp)
            view = strategy.scan({state.symbol: state, btc.symbol: btc}, NOW)["data"]
            trades = [t for t in view["open_trades"] if t["variant"] == "sc10"]
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0]["side"], "long")
            pos = strategy.trades[("sc10", state.symbol)].pos
            self.assertEqual(pos.stop_style, "sc10")
            self.assertFalse(any(c.get("episode") == "sc10" for c in view.get("candidates") or []))
            strategy.close()


class DayPnlTest(unittest.TestCase):
    def test_msk_day_and_equity_delta(self) -> None:
        from datetime import datetime

        from signal_engine.paper.analytics import MSK, compute_analytics, msk_day_start_ms

        noon = datetime(2026, 10, 13, 12, 0, tzinfo=MSK)
        now_ms = int(noon.timestamp() * 1000)
        start = msk_day_start_ms(now_ms)
        self.assertEqual(datetime.fromtimestamp(start / 1000.0, tz=MSK).hour, 0)
        self.assertEqual(datetime.fromtimestamp(start / 1000.0, tz=MSK).day, 13)
        with tempfile.TemporaryDirectory() as tmp:
            store = PaperStore(Path(tmp) / "paper.db")
            store.open()
            store.add_equity("t20", start - 3_600_000, 1000.0, 980.0, 0)
            store.insert_trade(
                {
                    "symbol": "XUSDT",
                    "variant": "t20",
                    "kind": "short",
                    "status": "closed",
                    "opened_at": start + 60_000,
                    "closed_at": start + 120_000,
                    "entry_price": 1.0,
                    "margin": 50.0,
                    "leverage": 10,
                    "notional": 500.0,
                    "qty": 500.0,
                    "liq_price": 1.1,
                    "stop_price": 1.0,
                    "best_price": 0.99,
                    "worst_price": 1.0,
                    "entry_fee": 0.0,
                    "funding_paid": 0.0,
                    "pnl_usd": 50.0,
                    "roe_pct": 10.0,
                    "exit_reason": "trailing_stop",
                }
            )
            stats = compute_analytics(store.db, {"t20": 1030.0}, now_ms=now_ms, unrealized={"t20": 0.0})
            t = stats["variants"]["t20"]["trades"]
            self.assertEqual(t["day_start_equity"], 980.0)
            self.assertAlmostEqual(t["day_pnl"], 50.0, places=2)
            self.assertAlmostEqual(t["day_pnl_pct"], 50.0 / 980.0 * 100.0, places=2)
            self.assertEqual(t["day_trades"], 1)
            store.close()

    def test_period_slices_skip_retired_variants(self) -> None:
        from datetime import datetime

        from signal_engine.paper.analytics import MSK, compute_analytics

        now = datetime(2026, 10, 15, 16, 0, tzinfo=MSK)
        now_ms = int(now.timestamp() * 1000)
        yesterday = datetime(2026, 10, 14, 12, 0, tzinfo=MSK)
        month_only = datetime(2026, 10, 1, 1, 0, tzinfo=MSK)
        before_month = datetime(2026, 9, 30, 18, 0, tzinfo=MSK)

        def closed(symbol: str, variant: str, when: datetime, pnl: float) -> dict:
            ts = int(when.timestamp() * 1000)
            return {
                "symbol": symbol,
                "variant": variant,
                "kind": "short",
                "status": "closed",
                "opened_at": ts - 60_000,
                "closed_at": ts,
                "entry_price": 1.0,
                "margin": 50.0,
                "leverage": 10,
                "notional": 500.0,
                "qty": 500.0,
                "liq_price": 1.1,
                "stop_price": 1.0,
                "best_price": 0.99,
                "worst_price": 1.0,
                "entry_fee": 0.0,
                "funding_paid": 0.0,
                "pnl_usd": pnl,
                "roe_pct": 10.0,
                "exit_reason": "trailing_stop",
            }

        with tempfile.TemporaryDirectory() as tmp:
            store = PaperStore(Path(tmp) / "paper.db")
            store.open()
            store.insert_trade(closed("AUSDT", "t20", yesterday, 40.0))
            store.insert_trade(closed("BUSDT", "t20", month_only, -10.0))
            store.insert_trade(closed("CUSDT", "t20", before_month, 5.0))
            store.insert_trade(closed("DUSDT", "v5", yesterday, -300.0))
            store.add_equity(
                "t20",
                int(datetime(2026, 10, 13, 23, 0, tzinfo=MSK).timestamp() * 1000),
                800.0,
                800.0,
                0,
            )
            stats = compute_analytics(store.db, {"t20": 1000.0}, now_ms=now_ms)
            self.assertNotIn("v5", stats["variants"])
            periods = stats["variants"]["t20"]["periods"]
            self.assertEqual(periods["all"]["n"], 3)
            self.assertEqual(periods["all"]["net"], 35.0)
            self.assertEqual(periods["all"]["base"], 1000.0)
            self.assertEqual(periods["all"]["net_pct"], 3.5)
            self.assertEqual(periods["month"]["n"], 2)
            self.assertEqual(periods["month"]["profit"], 40.0)
            self.assertEqual(periods["month"]["loss"], -10.0)
            self.assertEqual(periods["week"]["n"], 1)
            self.assertEqual(periods["week"]["net"], 40.0)
            self.assertEqual(periods["yesterday"]["n"], 1)
            self.assertEqual(periods["yesterday"]["win_pct"], 100.0)
            self.assertEqual(periods["yesterday"]["base"], 1000.0)
            self.assertEqual(periods["yesterday"]["profit_pct"], 4.0)
            self.assertEqual(periods["yesterday"]["net_pct"], 4.0)
            self.assertEqual(periods["month"]["base"], 1000.0)
            self.assertEqual(periods["week"]["base"], 1000.0)
            self.assertIn("Вчера", stats["period_labels"]["yesterday"])
            store.close()
