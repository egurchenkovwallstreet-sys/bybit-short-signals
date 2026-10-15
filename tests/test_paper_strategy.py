import tempfile
import unittest
from pathlib import Path

import config
from signal_engine.paper.analytics import compute_analytics
from signal_engine.paper.detect import (
    late_entry_extension_ok,
    double_top,
    evaluate,
    find_pump,
    paper_entry_blocks,
    cursor3_view,
    mini_pump_floors,
    mini_view,
    Evaluation,
    round_level_near,
    strong_top,
)
from signal_engine.paper.position import (
    Position,
    liquidation_price,
    long_liquidation_price,
    net_roe_stop_price,
    price_for_roe,
    trail_distance_pct,
    trail_stop,
    trail_stop_long,
)
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
        # пик 100% → трейл пик−20 = 80% → 0.92
        self.assertAlmostEqual(pos.stop_price, 0.92)
        self.assertIsNone(pos.update(0.7, 0.9, 0.7))
        # пик 300% → 280% → 0.72
        self.assertAlmostEqual(pos.stop_price, 0.72)
        self.assertEqual(pos.update(0.7, 0.72, 0.72), "trailing_stop")
        result = pos.close_result("trailing_stop")
        gross = (1.0 - 0.72) * 500
        fees = 500 * config.PAPER_FEE_RATE_TAKER + 500 / 1.0 * 0.72 * config.PAPER_FEE_RATE_TAKER
        self.assertAlmostEqual(result["pnl_usd"], gross - fees, places=6)

    def test_net_half_at_three_pct_then_lock_five_at_seven(self) -> None:
        pos = Position("X", 0, 1.0, 50.0)
        self.assertIsNone(pos.update(0.998, 1.0, 0.998))
        self.assertAlmostEqual(pos.max_roe(), 2.0)
        self.assertAlmostEqual(pos.stop_price, pos.liq_price)
        self.assertIsNone(pos.update(0.997, 1.0, 0.997))
        self.assertAlmostEqual(pos.max_roe(), 3.0)
        lock = net_roe_stop_price(1.0, 50.0, config.PAPER_BE_LOCK_NET_ROE, 10, pos.entry_fee)
        self.assertAlmostEqual(pos.stop_price, lock)
        self.assertIsNone(pos.update(0.993, 0.997, 0.993))
        self.assertAlmostEqual(pos.max_roe(), 7.0)
        self.assertAlmostEqual(pos.stop_price, 0.995)
        self.assertEqual(pos.update(0.993, 0.995, 0.995), "trailing_stop")

    def test_long_trail_be_lock(self) -> None:
        pos = Position("X", 0, 1.0, 50.0, side="long")
        self.assertIsNone(pos.update(1.0, 1.01, 1.01))
        self.assertGreater(pos.max_roe(), 0)
        self.assertIsNone(pos.update(1.008, 1.105, 1.105))
        self.assertGreaterEqual(pos.max_roe(), 10.0)
        stop = pos.stop_price
        self.assertEqual(pos.update(stop - 0.001, stop + 0.001, stop), "trailing_stop")

    def test_loss_cap_after_minus(self) -> None:
        pos = Position("X", 0, 1.0, 50.0)
        self.assertIsNone(pos.update(1.0, 1.01, 1.01))
        self.assertTrue(pos.loss_cap_armed)
        cap = net_roe_stop_price(1.0, 50.0, config.PAPER_LOSS_CAP_ROE, 10, pos.entry_fee)
        self.assertAlmostEqual(pos.stop_price, cap)
        self.assertLess(pos.stop_price, pos.liq_price)
        self.assertEqual(pos.update(1.0, pos.stop_price + 0.001, pos.stop_price), "trailing_stop")
        result = pos.close_result("trailing_stop")
        self.assertAlmostEqual(result["roe_pct"], config.PAPER_LOSS_CAP_ROE, places=1)

    def test_net_half_stop_after_three_pct(self) -> None:
        pos = Position("X", 0, 1.0, 50.0)
        self.assertIsNone(pos.update(0.997, 1.0, 0.997))
        self.assertAlmostEqual(pos.max_roe(), 3.0)
        stop = net_roe_stop_price(1.0, 50.0, config.PAPER_BE_LOCK_NET_ROE, 10, pos.entry_fee)
        self.assertAlmostEqual(pos.stop_price, stop)
        self.assertEqual(pos.update(stop, stop + 0.001, stop), "trailing_stop")
        result = pos.close_result("trailing_stop")
        self.assertAlmostEqual(result["roe_pct"], config.PAPER_BE_LOCK_NET_ROE, places=1)

    def test_p10_locks_net_half_after_three_pct(self) -> None:
        pos = Position("X", 0, 1.0, 50.0, peak_gap_roe=10.0)
        self.assertIsNone(pos.update(0.998, 1.0, 0.998))
        self.assertAlmostEqual(pos.max_roe(), 2.0)
        self.assertAlmostEqual(pos.stop_price, pos.liq_price)
        self.assertIsNone(pos.update(0.997, 1.0, 0.997))
        self.assertAlmostEqual(pos.max_roe(), 3.0)
        self.assertAlmostEqual(
            pos.stop_price,
            net_roe_stop_price(1.0, 50.0, config.PAPER_BE_LOCK_NET_ROE, 10, pos.entry_fee),
        )

    def test_peak_gap_not_before_ten_roe(self) -> None:
        pos = Position("X", 0, 1.0, 50.0, peak_gap_roe=10.0)
        self.assertIsNone(pos.update(0.999, 1.0, 0.999))
        self.assertAlmostEqual(pos.max_roe(), 1.0)
        self.assertAlmostEqual(pos.stop_price, pos.liq_price)
        self.assertIsNone(pos.update(0.995, 1.0, 0.995))
        self.assertAlmostEqual(pos.max_roe(), 5.0)
        self.assertAlmostEqual(
            pos.stop_price,
            net_roe_stop_price(1.0, 50.0, config.PAPER_BE_LOCK_NET_ROE, 10, pos.entry_fee),
        )

    def test_p10_at_ten_locks_net_two(self) -> None:
        pos = Position("X", 0, 1.0, 50.0, peak_gap_roe=10.0)
        self.assertIsNone(pos.update(0.99, 1.0, 0.99))
        self.assertAlmostEqual(pos.max_roe(), 10.0)
        lock2 = net_roe_stop_price(1.0, 50.0, config.PAPER_PLUS10_LOCK_NET_ROE, 10, pos.entry_fee)
        self.assertAlmostEqual(pos.stop_price, lock2)
        self.assertLess(pos.stop_price, price_for_roe(1.0, 0.0, 10))

    def test_t20_at_ten_keeps_five_floor(self) -> None:
        pos = Position("X", 0, 1.0, 50.0)
        self.assertIsNone(pos.update(0.99, 1.0, 0.99))
        self.assertAlmostEqual(pos.max_roe(), 10.0)
        lock2 = net_roe_stop_price(1.0, 50.0, config.PAPER_PLUS10_LOCK_NET_ROE, 10, pos.entry_fee)
        self.assertAlmostEqual(pos.stop_price, 0.995)
        self.assertLess(pos.stop_price, lock2)

    def test_peak_gap_locks_ten_pp_behind(self) -> None:
        # t20: пик 40% → max(5, 20) = 20% → 0.98. p10: лок 30% → 0.97.
        self.assertAlmostEqual(trail_stop(1.0, 0.96, 10), 0.98)
        self.assertAlmostEqual(trail_stop(1.0, 0.96, 10, peak_gap_roe=10.0), 0.97)

    def test_p10_position_uses_peak_gap(self) -> None:
        pos = Position("X", 0, 1.0, 50.0, peak_gap_roe=10.0)
        self.assertIsNone(pos.update(0.9, 1.0, 0.9))
        self.assertAlmostEqual(pos.stop_price, 0.91)

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
            # 5 из 9 есть: входят t20 и p10. Cursor SS ждёт дамп и сюда не лезет.
            shorts = sorted(t["variant"] for t in view["open_trades"] if t["variant"] in ("t20", "p10"))
            self.assertEqual(shorts, ["p10", "t20"])
            trade = view["open_trades"][0]
            self.assertAlmostEqual(trade["entry_price"], 1.35)
            self.assertAlmostEqual(trade["margin"], 50.0)
            self.assertAlmostEqual(strategy.balances["p10"], config.PAPER_START_BALANCE_USD)
            self.assertNotIn("v5", strategy.balances)
            self.assertNotIn("v9", strategy.balances)
            self.assertNotIn("dt", strategy.balances)

            state.bars_1m.append(Bar(NOW + MIN, 1.3, 1.3, 1.2, 1.2, 10.0))
            state.last_price = 1.2
            strategy.scan(states, NOW + MIN + 5000)
            self.assertIn(("t20", state.symbol), strategy.trades)

            state.bars_1m.append(Bar(NOW + 2 * MIN, 1.2, 1.33, 1.2, 1.32, 10.0))
            state.last_price = 1.32
            strategy.scan(states, NOW + 2 * MIN + 5000)
            self.assertNotIn(("t20", state.symbol), strategy.trades)
            self.assertNotIn(("p10", state.symbol), strategy.trades)
            self.assertGreater(strategy.balances["t20"], config.PAPER_START_BALANCE_USD)
            self.assertGreater(strategy.balances["p10"], config.PAPER_START_BALANCE_USD)

            stats = compute_analytics(store.db, strategy.balances)
            self.assertEqual(stats["variants"]["t20"]["trades"]["closed"], 1)
            self.assertEqual(stats["variants"]["t20"]["trades"]["wins"], 1)
            self.assertEqual(stats["variants"]["p10"]["trades"]["closed"], 1)
            self.assertEqual(strategy.candidates[state.symbol].entered, ["t20", "p10", "mln"])
            strategy.close()

    def test_balance_restored_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.db"
            store = PaperStore(path)
            strategy = PaperStrategy(store)
            strategy.open()
            state = pumped_state()
            strategy.tape.symbols[state.symbol] = pumped_tape()
            states = {state.symbol: state}
            strategy.scan(states, NOW)
            state.bars_1m.append(Bar(NOW + MIN, 1.3, 1.33, 1.2, 1.32, 10.0))
            state.last_price = 1.32
            strategy.scan(states, NOW + 2 * MIN + 5000)
            balance_after_close = strategy.balances["t20"]
            self.assertGreater(balance_after_close, config.PAPER_START_BALANCE_USD)
            strategy.close()

            strategy2 = PaperStrategy(PaperStore(path))
            strategy2.open()
            self.assertAlmostEqual(strategy2.balances["t20"], balance_after_close)
            stats = compute_analytics(strategy2.store.db, strategy2.balances)
            self.assertAlmostEqual(
                stats["variants"]["t20"]["trades"]["balance"],
                balance_after_close,
                places=2,
            )
            strategy2.close()

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
            # 8 из 9: вход в t20 и p10, теневая сделка по недостающему условию.
            shorts = sorted(t["variant"] for t in view["open_trades"] if t["variant"] in ("t20", "p10"))
            self.assertEqual(shorts, ["p10", "t20"])
            pumps = [c for c in view["candidates"] if c.get("episode") not in ("css", "css2", "growth", "sc10")]
            self.assertEqual(len(pumps), 1)
            self.assertEqual(pumps[0]["shadow"]["missing"], "short_liq_faded")
            self.assertEqual(len(strategy.shadows), 1)
            strategy.close()

    def test_restart_keeps_candidate_and_tape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.db"
            strategy = PaperStrategy(PaperStore(path))
            strategy.open()
            state = pumped_state()
            strategy.tape.symbols[state.symbol] = pumped_tape()
            strategy.scan({state.symbol: state}, NOW)
            self.assertIn(state.symbol, strategy.candidates)
            strategy.close()

            restarted = PaperStrategy(PaperStore(path))
            restarted.open()
            self.assertIn(state.symbol, restarted.candidates)
            self.assertEqual(restarted.candidates[state.symbol].entered, ["t20", "p10", "mln"])
            self.assertEqual(len(restarted.trades), 3)
            tape = restarted.tape.symbols[state.symbol]
            self.assertTrue(tape.minutes)
            self.assertTrue(tape.liq_short)

            # Свечи ещё не подгрузились: памп не виден, но кандидата не снимаем.
            empty = SymbolState(state.symbol)
            empty.last_price = 1.35
            restarted.scan({state.symbol: empty}, NOW + MIN)
            self.assertIn(state.symbol, restarted.candidates)
            restarted.close()


    def test_duplicate_active_candidates_collapse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PaperStore(Path(tmp) / "paper.db")
            store.open()
            for peak_ts in (NOW - 5 * 3_600_000, NOW - 3_600_000):
                store.insert_candidate(
                    {"symbol": "DUPUSDT", "kind": "short", "status": "watching", "started_at": 1,
                     "updated_at": 1, "peak_ts": peak_ts, "peak_price": 2.0, "valley_price": 1.0,
                     "valley_ts": 1, "growth_pct": 100.0}
                )
            store.close()
            strategy = PaperStrategy(PaperStore(Path(tmp) / "paper.db"))
            strategy.open()
            self.assertEqual(strategy.candidates["DUPUSDT"].pump.peak_ts, NOW - 3_600_000)
            self.assertEqual(len(strategy.store.active_candidates()), 1)
            strategy.close()


class StrongTopTest(unittest.TestCase):
    @staticmethod
    def _bars(first: float, second: float, gap: int, after: int) -> list[Bar]:
        hour = 3_600_000
        highs = [1.5] * 10 + [first] + [1.5] * gap + [second] + [1.5] * after
        return [Bar(i * hour, 1.4, h, 1.3, 1.4, 10.0) for i, h in enumerate(highs)]

    def _find(self, bars: list[Bar]):
        now = (len(bars) + 1) * 3_600_000
        return strong_top({"60": bars}, now)

    def test_lower_second_top_found(self) -> None:
        found = self._find(self._bars(2.0, 1.85, gap=5, after=3))
        assert found is not None
        self.assertEqual(found["second_price"], 1.85)
        self.assertLess(found["diff_pct"], 10)

    def test_rejects_higher_second_or_wide_gap_or_too_fresh(self) -> None:
        self.assertIsNone(self._find(self._bars(2.0, 2.05, gap=5, after=3)))
        self.assertIsNone(self._find(self._bars(2.0, 1.75, gap=5, after=3)))
        self.assertIsNone(self._find(self._bars(2.0, 1.85, gap=3, after=3)))
        self.assertIsNone(self._find(self._bars(2.0, 1.85, gap=5, after=0)))

    def test_variants_by_passed_count(self) -> None:
        state, tape = pumped_state(), pumped_tape()
        pump = find_pump(state, tape, NOW)
        assert pump is not None
        ev = evaluate(state, tape, pump, {}, None, NOW)
        for key in list(ev.checks)[:5]:
            ev.checks[key]["ok"] = False
        self.assertEqual(ev.passed_count, 4)
        self.assertEqual(ev.variants, [])
        ev.strong_top = {"interval": "60"}
        self.assertEqual(ev.variants, [])
        ev.checks["stall"]["ok"] = True
        self.assertEqual(ev.variants, ["t20", "p10", "mln"])


class EntryGateTest(unittest.TestCase):
    def _eval(self):
        state, tape = pumped_state(), pumped_tape()
        pump = find_pump(state, tape, NOW)
        assert pump is not None
        return evaluate(state, tape, pump, {}, None, NOW)

    def test_fixture_passes_gate(self) -> None:
        ev = self._eval()
        self.assertEqual(ev.entry_blocked, [])
        self.assertIn("t20", ev.variants)
        self.assertIn("p10", ev.variants)

    def test_blocks_14d(self) -> None:
        ev = self._eval()
        ev.metrics["pump"]["trigger"] = "14d"
        self.assertEqual(ev.entry_blocked, ["no_14d"])
        self.assertEqual(ev.variants, [])

    def test_blocks_too_soon_and_too_late(self) -> None:
        ev = self._eval()
        ev.metrics["since_peak_min"] = 0
        self.assertIn("since_too_soon", ev.entry_blocked)
        self.assertEqual(ev.variants, [])
        ev.metrics["since_peak_min"] = 181
        ev.metrics["oi_1h_pct"] = 1.0
        self.assertIn("since_too_late", ev.entry_blocked)

    def test_blocks_late_megavol_and_double_top(self) -> None:
        ev = self._eval()
        ev.metrics["since_peak_min"] = 90
        ev.metrics["pump"]["volume_ratio"] = 80
        self.assertEqual(ev.entry_blocked, ["late_megavol"])
        ev.metrics["pump"]["volume_ratio"] = 20
        ev.metrics["double_top"] = {"interval": "60"}
        self.assertEqual(ev.entry_blocked, ["late_double_top"])
        ev.metrics["since_peak_min"] = 40
        self.assertEqual(ev.entry_blocked, [])
        self.assertIn("t20", ev.variants)

    def test_late_entry_extension_after_180_min(self) -> None:
        base = {
            "pump": {"trigger": "4h", "volume_ratio": 10},
            "since_peak_min": 200,
            "drawdown_from_peak_pct": 20.0,
            "oi_1h_pct": -1.5,
            "oi_4h_pct": -0.8,
            "volume_ratio_20m": 0.5,
            "sell_share": {"5m": 65.0, "10m": 62.0, "15m": 61.0},
        }
        self.assertTrue(late_entry_extension_ok(base))
        self.assertNotIn("since_too_late", paper_entry_blocks(base))
        bad = {**base, "drawdown_from_peak_pct": 31.0}
        self.assertFalse(late_entry_extension_ok(bad))
        self.assertIn("since_too_late", paper_entry_blocks(bad))

    def test_paper_entry_blocks_helper(self) -> None:
        self.assertEqual(
            paper_entry_blocks({"pump": {"trigger": "4h", "volume_ratio": 10}, "since_peak_min": 30}),
            [],
        )
        self.assertIn("no_14d", paper_entry_blocks({"pump": {"trigger": "14d"}, "since_peak_min": 30}))

    def test_stale_last_eval_hides_blocked_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.db"
            store = PaperStore(path)
            store.open()
            store.insert_candidate(
                {
                    "symbol": "NIGHTUSDT",
                    "kind": "long",
                    "status": "watching",
                    "started_at": 1,
                    "updated_at": 1,
                    "peak_ts": NOW - 2000 * MIN,
                    "peak_price": 2.0,
                    "valley_price": 1.0,
                    "valley_ts": 1,
                    "growth_pct": 120.0,
                    "last_eval": {
                        "metrics": {
                            "pump": {"trigger": "14d", "volume_ratio": 20},
                            "since_peak_min": 2000,
                        },
                        "variants": ["t20", "p10"],
                        "passed_count": 6,
                    },
                }
            )
            store.close()
            strategy = PaperStrategy(PaperStore(path))
            strategy.open()
            view = strategy.view(NOW, None)
            pumps = [c for c in view["candidates"] if c.get("episode") not in ("css", "css2", "growth", "sc10")]
            self.assertEqual(len(pumps), 1)
            ev = pumps[0]["eval"]
            self.assertIn("no_14d", ev["entry_blocked"])
            self.assertIn("since_too_late", ev["entry_blocked"])
            self.assertEqual(ev["variants"], [])
            self.assertIn("Вход закрыт", pumps[0]["note"] or "")
            strategy.close()

    def test_strategy_skips_late_peak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PaperStore(Path(tmp) / "paper.db")
            strategy = PaperStrategy(store)
            strategy.open()
            state = pumped_state()
            strategy.tape.symbols[state.symbol] = pumped_tape()
            view = strategy.scan({state.symbol: state}, NOW + 100 * MIN)["data"]
            shorts = [t for t in view["open_trades"] if t["variant"] in ("t20", "p10")]
            self.assertEqual(shorts, [])
            pumps = [c for c in view["candidates"] if c.get("episode") not in ("css", "css2", "growth", "sc10")]
            self.assertTrue(pumps)
            blocked = (pumps[0].get("eval") or {}).get("entry_blocked") or []
            self.assertIn("since_too_late", blocked)
            strategy.close()


def _c3_metrics() -> dict:
    return {
        "pump": {"trigger": "24h"},
        "since_peak_min": 55,
        "drawdown_from_peak_pct": 4.0,
        "price_20m_pct": 1.2,
        "buys_fade_ratio": 0.4,
        "long_liq_15m_usd": 0,
        "ema_broken": [],
    }


class Cursor3EntryTest(unittest.TestCase):
    def test_all_eight_pass(self) -> None:
        view = cursor3_view(_c3_metrics(), 8.0)
        self.assertTrue(view["passed"])
        self.assertEqual(view["passed_count"], 8)
        self.assertEqual(view["variants"], ["c3"])
        self.assertEqual(config.paper_stop_style("c3"), "default")
        self.assertEqual(config.paper_peak_gap_roe("c3"), 0.0)

    def test_each_rule_blocks(self) -> None:
        cases = {
            "trigger_4h_24h": {"pump": {"trigger": "7d"}},
            "since_peak": {"since_peak_min": 5},
            "drawdown": {"drawdown_from_peak_pct": 10.1},
            "price_20m": {"price_20m_pct": -0.1},
            "buys_faded": {"buys_fade_ratio": 0.51},
            "long_liq_quiet": {"long_liq_15m_usd": 201},
            "ema_intact": {"ema_broken": ["15m_EMA50"]},
        }
        for key, patch in cases.items():
            metrics = _c3_metrics()
            metrics.update(patch)
            if "pump" in patch:
                metrics["pump"] = patch["pump"]
            failed = cursor3_view(metrics, 8.0)["failed"]
            self.assertEqual(failed, [key], key)
        self.assertEqual(cursor3_view(_c3_metrics(), 12.1)["failed"], ["score_cap"])
        self.assertEqual(cursor3_view(_c3_metrics(), 12.0)["failed"], [])

    def test_missing_value_blocks(self) -> None:
        metrics = _c3_metrics()
        metrics["price_20m_pct"] = None
        metrics["buys_fade_ratio"] = None
        self.assertEqual(
            cursor3_view(metrics, 8.0)["failed"],
            ["price_20m", "buys_faded"],
        )

    def test_edges_inclusive(self) -> None:
        metrics = _c3_metrics()
        metrics["since_peak_min"] = 180
        metrics["drawdown_from_peak_pct"] = 10
        metrics["price_20m_pct"] = 0
        metrics["buys_fade_ratio"] = 0.5
        metrics["long_liq_15m_usd"] = 200
        self.assertEqual(cursor3_view(metrics, 12)["failed"], [])
        metrics["since_peak_min"] = 181
        self.assertIn("since_peak", cursor3_view(metrics, 12)["failed"])


def _mini_metrics() -> dict:
    return {
        "pump": {"trigger": "4h", "volume_ratio": 12},
        "since_peak_min": 40,
        "drawdown_from_peak_pct": 4.0,
        "price_20m_pct": 0.4,
        "buys_fade_ratio": 0.3,
        "long_liq_15m_usd": 0,
        "ema_broken": [],
    }


def _mini_ev(metrics: dict, score: float = 8.0, passed: int = 9) -> Evaluation:
    keys = (
        "pump_volume",
        "pump_buys",
        "stall",
        "buys_faded",
        "sells_dominate",
        "volume_fade",
        "short_liq_faded",
        "oi_1h_negative",
        "btc_guard",
    )
    checks = {key: {"ok": i < passed, "value": 1, "need": "x"} for i, key in enumerate(keys)}
    return Evaluation(checks, metrics, score, {}, False)


class MiniTestEntryTest(unittest.TestCase):
    def test_soft_floors_are_forty_percent_lower(self) -> None:
        floors = mini_pump_floors()
        self.assertEqual(floors["4h"], 18)
        self.assertEqual(floors["24h"], 30)
        self.assertEqual(floors["7d"], 48)
        self.assertEqual(floors["14d"], 60)
        self.assertIsNone(find_pump(pumped_state(), pumped_tape(), NOW, {"4h": 99, "24h": 99, "7d": 99, "14d": 99}))
        soft = find_pump(pumped_state(), pumped_tape(), NOW, floors)
        self.assertIsNotNone(soft)

    def test_passes_with_sample_gate_and_loss_cuts(self) -> None:
        view = mini_view(_mini_ev(_mini_metrics()))
        self.assertTrue(view["passed"])
        self.assertEqual(view["variants"], ["mt1", "mt2"])
        self.assertEqual(config.paper_peak_gap_roe("mt1"), 0.0)
        self.assertEqual(config.paper_peak_gap_roe("mt2"), config.PAPER_TRAIL_PEAK_GAP_ROE)
        self.assertEqual(config.paper_stop_style("mt1"), "default")
        self.assertEqual(config.paper_stop_style("mt2"), "default")

    def test_late_extension_does_not_open_mini(self) -> None:
        metrics = _mini_metrics()
        metrics.update(
            {
                "since_peak_min": 200,
                "drawdown_from_peak_pct": 8.0,
                "oi_1h_pct": -1.0,
                "oi_4h_pct": -1.0,
                "volume_ratio_20m": 0.4,
                "sell_share": {"5m": 70.0, "10m": 68.0, "15m": 66.0},
            }
        )
        failed = mini_view(_mini_ev(metrics))["failed"]
        self.assertIn("since_peak", failed)
        self.assertNotIn("five_of_nine", failed)

    def test_loss_profile_is_blocked(self) -> None:
        metrics = _mini_metrics()
        metrics["pump"] = {"trigger": "7d", "volume_ratio": 12}
        self.assertIn("trigger_4h_24h", mini_view(_mini_ev(metrics))["failed"])
        metrics = _mini_metrics()
        metrics["drawdown_from_peak_pct"] = 12
        self.assertEqual(mini_view(_mini_ev(metrics))["failed"], ["drawdown"])
        metrics = _mini_metrics()
        metrics["price_20m_pct"] = -0.2
        self.assertEqual(mini_view(_mini_ev(metrics))["failed"], ["price_20m"])
        metrics = _mini_metrics()
        metrics["long_liq_15m_usd"] = 9000
        self.assertEqual(mini_view(_mini_ev(metrics))["failed"], ["long_liq_quiet"])
        metrics = _mini_metrics()
        metrics["ema_broken"] = ["15m_EMA50"]
        self.assertEqual(mini_view(_mini_ev(metrics))["failed"], ["ema_intact"])
        self.assertEqual(mini_view(_mini_ev(_mini_metrics(), score=15))["failed"], ["score_cap"])
        self.assertIn("five_of_nine", mini_view(_mini_ev(_mini_metrics(), passed=4))["failed"])


if __name__ == "__main__":
    unittest.main()
