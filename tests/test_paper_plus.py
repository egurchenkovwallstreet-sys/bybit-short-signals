import tempfile
import unittest
from pathlib import Path

import config
from signal_engine.paper.detect import evaluate, find_pump
from signal_engine.paper.plus_detect import evaluate_plus, plus_hit_first_stop
from signal_engine.paper.store import PaperStore
from signal_engine.paper.strategy import PaperStrategy
from tests.test_paper_strategy import MIN, NOW, pumped_state, pumped_tape


def boost_sells(tape, now: int) -> None:
    for minutes_ago in range(14, -1, -1):
        extra = 800.0 if minutes_ago < 5 else 200.0
        tape.add_trade(now - minutes_ago * MIN, "Sell", extra)


def plus_eval(state, tape, now: int):
    pump = find_pump(state, tape, now)
    assert pump is not None
    base = evaluate(state, tape, pump, {}, None, now)
    return pump, evaluate_plus(state, tape, {}, now, base)


class PlusEntryTest(unittest.TestCase):
    def test_flat_sells_do_not_pass(self) -> None:
        state, tape = pumped_state(), pumped_tape()
        _, plus = plus_eval(state, tape, NOW)
        self.assertTrue(plus.checks["no_new_high"]["ok"])
        self.assertTrue(plus.checks["sells_55"]["ok"])
        self.assertFalse(plus.checks["sell_volume_up"]["ok"])
        self.assertFalse(plus.passed)
        self.assertEqual(plus.to_data()["variants"], [])

    def test_all_rules_pass_when_sells_grow(self) -> None:
        state, tape = pumped_state(), pumped_tape()
        boost_sells(tape, NOW)
        _, plus = plus_eval(state, tape, NOW)
        self.assertEqual(plus.failed, [], plus.checks)
        self.assertEqual(plus.to_data()["variants"], list(config.PAPER_PLUS_VARIANTS))

    def test_new_high_in_last_seven_blocks(self) -> None:
        state, tape = pumped_state(), pumped_tape()
        boost_sells(tape, NOW)
        for bar in state.bars_1m:
            if NOW - bar.timestamp <= 35 * MIN:
                bar.high = 1.50
        _, plus = plus_eval(state, tape, NOW)
        self.assertFalse(plus.checks["no_new_high"]["ok"])
        self.assertFalse(plus.passed)

    def test_short_history_blocks(self) -> None:
        state, tape = pumped_state(), pumped_tape()
        boost_sells(tape, NOW)
        state.bars_1m = state.bars_1m[-10:]
        _, plus = plus_eval(state, tape, NOW)
        self.assertFalse(plus.checks["no_new_high"]["ok"])

    def test_rising_oi_blocks(self) -> None:
        state, tape = pumped_state(), pumped_tape()
        boost_sells(tape, NOW)
        state.oi_5m = [(NOW - (48 - i) * 5 * MIN, 1000.0 + i * 10) for i in range(49)]
        _, plus = plus_eval(state, tape, NOW)
        self.assertFalse(plus.checks["oi_not_rising"]["ok"])

    def test_missing_oi_blocks(self) -> None:
        state, tape = pumped_state(), pumped_tape()
        boost_sells(tape, NOW)
        state.oi_5m = []
        _, plus = plus_eval(state, tape, NOW)
        self.assertFalse(plus.checks["oi_not_rising"]["ok"])

    def test_high_volume_is_not_falling_even_if_price_drops(self) -> None:
        state, tape = pumped_state(), pumped_tape()
        boost_sells(tape, NOW)
        for bar in state.bars_1m:
            if NOW - bar.timestamp <= 20 * MIN:
                bar.volume = 500.0
        state.last_price = 1.32
        _, plus = plus_eval(state, tape, NOW)
        self.assertFalse(plus.checks["volume_falling"]["ok"])

    def test_late_and_deep_blocks_shallow_late_does_not(self) -> None:
        state, tape = pumped_state(), pumped_tape()
        boost_sells(tape, NOW)
        pump = find_pump(state, tape, NOW)
        assert pump is not None
        pump.peak_ts = NOW - 200 * MIN
        state.last_price = pump.peak_price * 0.80
        base = evaluate(state, tape, pump, {}, None, NOW)
        deep = evaluate_plus(state, tape, {}, NOW, base)
        self.assertFalse(deep.checks["not_late_deep"]["ok"])

        state.last_price = pump.peak_price * 0.90
        base = evaluate(state, tape, pump, {}, None, NOW)
        shallow = evaluate_plus(state, tape, {}, NOW, base)
        self.assertTrue(shallow.checks["not_late_deep"]["ok"])

    def test_first_stop_detector(self) -> None:
        self.assertTrue(plus_hit_first_stop("t20p", -15.0, 0.4))
        self.assertTrue(plus_hit_first_stop("p10p", -100.0, 0.0))
        self.assertFalse(plus_hit_first_stop("t20p", -0.4, 2.0))
        self.assertFalse(plus_hit_first_stop("t20p", -15.0, 4.0))
        self.assertTrue(plus_hit_first_stop("mlnp", -10.0, 0.5))
        self.assertFalse(plus_hit_first_stop("mlnp", -10.0, 3.0))
        self.assertFalse(plus_hit_first_stop("t20", -15.0, 0.0))


class PlusStrategyTest(unittest.TestCase):
    def test_copies_open_then_same_peak_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strategy = PaperStrategy(PaperStore(Path(tmp) / "paper.db"))
            strategy.open()
            state = pumped_state()
            tape = pumped_tape()
            boost_sells(tape, NOW)
            strategy.tape.symbols[state.symbol] = tape
            view = strategy.scan({state.symbol: state}, NOW)["data"]
            opened = {t["variant"] for t in view["open_trades"]}
            self.assertTrue(set(config.PAPER_PLUS_VARIANTS) <= opened)
            self.assertEqual(strategy.trades[("t20p", state.symbol)].pos.peak_gap_roe, 0.0)
            if config.PAPER_MLNP_VARIANT in config.PAPER_PLUS_VARIANTS:
                self.assertEqual(strategy.trades[("mlnp", state.symbol)].pos.stop_style, "mln")
            self.assertEqual(strategy.trades[("t20p", state.symbol)].pos.stop_style, "default")

            state.last_price = 1.370
            strategy.scan({state.symbol: state}, NOW + 1000)
            self.assertFalse(any(v in config.PAPER_PLUS_VARIANTS for v, _ in strategy.trades))
            peak_ts = next(iter(strategy.plus_blocked[state.symbol]))
            self.assertGreater(peak_ts, 0)

            later = NOW + 6 * MIN
            for minutes_ago in range(4, -1, -1):
                tape.add_trade(later - minutes_ago * MIN, "Sell", 5000.0)
            strategy.scan({state.symbol: state}, later)
            self.assertFalse(any(v in config.PAPER_PLUS_VARIANTS for v, _ in strategy.trades))
            note = strategy.candidates[state.symbol].note or ""
            self.assertIn("первым стопом", note)
            strategy.close()
