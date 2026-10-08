import tempfile
import unittest
from pathlib import Path

import config
from signal_engine.paper.analytics import compute_analytics
from signal_engine.paper.detect import double_top, evaluate, find_pump, round_level_near
from signal_engine.paper.position import Position, liquidation_price, trail_distance_pct
from signal_engine.paper.store import PaperStore
from signal_engine.paper.strategy import PaperStrategy
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState

MIN = 60_000
NOW = (1_800_000_000_000 // 900_000) * 900_000


def pumped_state(symbol: str = "PUMPUSDT") -> SymbolState:
    """Плоско у 1.0, рост до 1.40 за 90 мин на объёме ×20, затем 90 мин стоим 1.325–1.375."""
    state = SymbolState(symbol)
    first_1m = NOW - 200 * MIN
    rest_end = (first_1m // (15 * MIN)) * 15 * MIN
    state.bars_htf["15"] = [
        Bar(rest_end - (130 - i) * 15 * MIN, 1.0, 1.01, 0.99, 1.0, 100.0) for i in range(130)
    ]
    state.bars_htf["240"] = [
        Bar(NOW - (60 - i) * 240 * MIN, 1.0, 1.01, 0.99, 1.0, 1000.0) for i in range(60)
    ]
    bars = []
    for i in range(200):
        ts = first_1m + i * MIN
        minutes_ago = (NOW - ts) // MIN
        if minutes_ago > 180:
            bars.append(Bar(ts, 1.0, 1.005, 0.995, 1.0, 7.0))
        elif minutes_ago > 90:
            frac = (180 - minutes_ago) / 90
            price = 1.0 + 0.395 * frac
            bars.append(Bar(ts, price, price + 0.004, price - 0.004, price, 133.0))
        elif minutes_ago == 90:
            bars.append(Bar(ts, 1.39, 1.40, 1.38, 1.39, 133.0))
        else:
            price = 1.35 + (0.025 if minutes_ago % 2 else -0.025)
            bars.append(Bar(ts, price, price, price, price, 20.0))
    state.bars_1m = bars
    state.last_price = 1.35
    state.turnover_24h_usdt = 5_000_000
    state.funding_rate = 0.0005
    state.oi_5m = [(NOW - (48 - i) * 5 * MIN, 1000.0 - i) for i in range(49)]
    return state


def pumped_tape() -> SymbolTape:
    tape = SymbolTape()
    for minutes_ago in range(179, -1, -1):
        ts = NOW - minutes_ago * MIN
        if minutes_ago > 90:
            tape.add_trade(ts, "Buy", 1000.0)
            tape.add_trade(ts, "Sell", 250.0)
        else:
            tape.add_trade(ts, "Buy", 50.0)
            tape.add_trade(ts, "Sell", 100.0)
    tape.add_liquidation(NOW - 10 * MIN, "Sell", 10_000.0)
    tape.add_liquidation(NOW - 5 * MIN, "Buy", 20_000.0)
    return tape


class TrailingTest(unittest.TestCase):
    def test_distance_schedule(self) -> None:
        self.assertEqual(trail_distance_pct(0), 10.0)
        self.assertEqual(trail_distance_pct(100), 10.0)
        self.assertAlmostEqual(trail_distance_pct(200), 6.0)
        self.assertEqual(trail_distance_pct(300), 2.0)
        self.assertEqual(trail_distance_pct(500), 2.0)

    def test_liquidation_before_ten_percent(self) -> None:
        self.assertAlmostEqual(liquidation_price(1.0), 1.095)

    def test_trailing_exit_locks_profit(self) -> None:
        pos = Position("X", 0, 1.0, 50.0)
        self.assertAlmostEqual(pos.stop_price, pos.liq_price)
        self.assertIsNone(pos.update(0.9, 1.0, 0.9))
        self.assertAlmostEqual(pos.stop_price, 0.99)
        self.assertIsNone(pos.update(0.7, 0.9, 0.7))
        self.assertAlmostEqual(pos.stop_price, 0.714)
        self.assertEqual(pos.update(0.7, 0.72, 0.72), "trailing_stop")
        result = pos.close_result("trailing_stop")
        gross = (1.0 - 0.714) * 500
        fees = 500 * config.PAPER_FEE_RATE_TAKER + 500 / 1.0 * 0.714 * config.PAPER_FEE_RATE_TAKER
        self.assertAlmostEqual(result["pnl_usd"], gross - fees, places=6)

    def test_liquidation_loses_margin(self) -> None:
        pos = Position("X", 0, 1.0, 50.0)
        self.assertEqual(pos.update(1.0, 1.1, 1.1), "liquidation")
        result = pos.close_result("liquidation")
        self.assertAlmostEqual(result["pnl_usd"], -50.0 - pos.entry_fee)

    def test_short_receives_positive_funding(self) -> None:
        pos = Position("X", 0, 2.0, 50.0, next_funding_ts=1000)
        paid = pos.apply_funding(1000, 0.001, 2.0)
        self.assertAlmostEqual(paid, 500 / 2.0 * 2.0 * 0.001)
        self.assertGreater(pos.funding_paid, 0)
        self.assertIsNone(pos.next_funding_ts)


class DetectTest(unittest.TestCase):
    def test_short_pump_detected(self) -> None:
        pump = find_pump(pumped_state(), pumped_tape(), NOW)
        self.assertIsNotNone(pump)
        assert pump is not None
        self.assertEqual(pump.kind, "short")
        self.assertEqual(pump.trigger, "4h")
        self.assertGreater(pump.growth_pct, 30)
        self.assertEqual(pump.peak_ts, NOW - 90 * MIN)
        self.assertGreaterEqual(pump.volume_ratio, 10)
        self.assertGreaterEqual(pump.buy_share_pct, 70)

    def test_all_conditions_pass(self) -> None:
        state, tape = pumped_state(), pumped_tape()
        pump = find_pump(state, tape, NOW)
        assert pump is not None
        ev = evaluate(state, tape, pump, {}, None, NOW)
        self.assertEqual(ev.failed, [])
        self.assertIn("long_liq", ev.score_parts)
        self.assertIn("funding", ev.score_parts)

    def test_ongoing_short_liquidations_block_entry(self) -> None:
        state, tape = pumped_state(), pumped_tape()
        tape.add_liquidation(NOW, "Sell", 9_000.0)
        pump = find_pump(state, tape, NOW)
        assert pump is not None
        ev = evaluate(state, tape, pump, {}, None, NOW)
        self.assertEqual(ev.failed, ["short_liq_faded"])

    def test_btc_rally_needs_ema_or_double_top(self) -> None:
        state, tape = pumped_state(), pumped_tape()
        pump = find_pump(state, tape, NOW)
        assert pump is not None
        ev = evaluate(state, tape, pump, {}, 4.0, NOW)
        self.assertEqual(ev.failed, ["btc_guard"])

    def test_weak_volume_rejected(self) -> None:
        state = pumped_state()
        for bar in state.bars_htf["15"]:
            bar.volume = 1000.0
        pump = find_pump(state, pumped_tape(), NOW)
        assert pump is not None
        ev = evaluate(state, pumped_tape(), pump, {}, None, NOW)
        self.assertIn("pump_volume", ev.failed)

    def test_double_top(self) -> None:
        hour = 3_600_000
        bars = []
        for i in range(60):
            high = 1.8
            if i == 20:
                high = 2.0
            elif i == 40:
                high = 1.97
            bars.append(Bar(i * hour, 1.7, high, 1.6, 1.7, 10.0))
        found = double_top(bars, "60", 10, 60 * hour)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found["bars_between"], 20)
        self.assertLessEqual(found["diff_pct"], 3)

    def test_round_level(self) -> None:
        level = round_level_near(0.995)
        assert level is not None
        self.assertEqual(level["level"], 1.0)
        self.assertEqual(level["weight"], 8.0)
        self.assertIsNone(round_level_near(0.93))


class StrategyCycleTest(unittest.TestCase):
    def test_open_trail_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PaperStore(Path(tmp) / "paper.db")
            strategy = PaperStrategy(store)
            strategy.open()
            state = pumped_state()
            strategy.tape.symbols[state.symbol] = pumped_tape()
            states = {state.symbol: state}

            view = strategy.scan(states, NOW)["data"]
            self.assertEqual(len(view["open_trades"]), 1)
            trade = view["open_trades"][0]
            self.assertAlmostEqual(trade["entry_price"], 1.35)
            self.assertAlmostEqual(trade["margin"], 50.0)

            state.bars_1m.append(Bar(NOW + MIN, 1.3, 1.3, 1.2, 1.2, 10.0))
            state.last_price = 1.2
            strategy.scan(states, NOW + MIN + 5000)
            self.assertIn(state.symbol, strategy.trades)

            state.bars_1m.append(Bar(NOW + 2 * MIN, 1.2, 1.33, 1.2, 1.32, 10.0))
            state.last_price = 1.32
            strategy.scan(states, NOW + 2 * MIN + 5000)
            self.assertNotIn(state.symbol, strategy.trades)
            self.assertGreater(strategy.balance, config.PAPER_START_BALANCE_USD)

            stats = compute_analytics(store.db, strategy.balance)
            self.assertEqual(stats["trades"]["closed"], 1)
            self.assertEqual(stats["trades"]["wins"], 1)
            self.assertEqual(stats["candidates"]["by_status"].get("entered"), 1)
            strategy.close()

    def test_near_miss_starts_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PaperStore(Path(tmp) / "paper.db")
            strategy = PaperStrategy(store)
            strategy.open()
            state = pumped_state()
            tape = pumped_tape()
            tape.add_liquidation(NOW, "Sell", 9_000.0)
            strategy.tape.symbols[state.symbol] = tape
            view = strategy.scan({state.symbol: state}, NOW)["data"]
            self.assertEqual(view["open_trades"], [])
            self.assertEqual(len(view["candidates"]), 1)
            self.assertEqual(view["candidates"][0]["shadow"]["missing"], "short_liq_faded")
            self.assertEqual(len(strategy.shadows), 1)
            strategy.close()


if __name__ == "__main__":
    unittest.main()
