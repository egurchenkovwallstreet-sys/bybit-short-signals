"""Проверки движка сигналов без Redis и без биржи."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from signal_engine.engine import Engine
from signal_engine.evaluate import Reading
from signal_engine.flow import (
    cvd_bearish,
    funding_extreme,
    obv_bearish,
    oi_falling,
    taker_ratio,
    volume_faded,
)
from signal_engine.indicators import obv_change, rsi
from signal_engine.levels import (
    Candle,
    candle_swept_level,
    classify_level,
    find_pivot_highs,
    level_score,
    round_level_confirmed,
    round_step,
    score_level,
    sweep_on_timeframe,
)
from signal_engine.liquidations import is_short_liquidation, liquidations_faded, window_notionals
from signal_engine.outcomes import classify_outcome, short_pnl_pct
from signal_engine.pump import detect_pump, price_change_pct
from signal_engine.rating import column_for, expert_probability, probability_pct, signal_rating, sort_by_rating
from signal_engine.state import SymbolState
from signal_engine.store import SignalStore


START = 1_700_006_400_000
HOUR = 3_600_000


def _pump_closes() -> list[float]:
    """Рост за 15 минут есть, за последние 5 минут уже откат. RSI остаётся в 60–85."""
    price = 100.0
    prefix: list[float] = []
    for index in range(24):
        price *= 1.001 if index % 2 == 0 else 0.9995
        prefix.append(price)
    base = prefix[-1]
    spike = base * 1.07
    end = base * 1.055
    path = [base]
    for index in range(1, 8):
        path.append(base + (spike - base) * index / 7)
    for index in range(1, 9):
        path.append(spike + (end - spike) * index / 8)
    return prefix + path


def _klines(symbol: str, closes: list[float], volumes: list[float]) -> dict:
    candles = []
    for index, (close, volume) in enumerate(zip(closes, volumes)):
        candles.append(
            {
                "timestamp": START + index * 60_000,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": volume,
            }
        )
    return {
        "symbol": symbol,
        "timestamp": candles[-1]["timestamp"],
        "type": "kline",
        "data": {"interval": "1", "candles": candles},
    }


def _engine(folder: str) -> tuple[Engine, SignalStore]:
    store = SignalStore(Path(folder) / "signals.db")
    store.open()
    engine = Engine(store)
    return engine, store


class IndicatorTest(unittest.TestCase):
    def test_rsi_wilder_period_two(self) -> None:
        # Закрытия 10, 12, 11, 13. Второе значение RSI Уайлдера для периода 2 — 85.714...
        value = rsi([10, 12, 11, 13], 2)
        self.assertIsNotNone(value)
        self.assertAlmostEqual(value or 0, 100 - 100 / 7, places=4)

    def test_obv_change(self) -> None:
        change = obv_change([1, 2, 1, 2], [0, 10, 30, 5], 2)
        self.assertAlmostEqual(change or 0, -25)


class PumpTest(unittest.TestCase):
    def test_fifteen_minutes_without_five_minute_spike(self) -> None:
        closes = _pump_closes()
        volumes = [10.0] * (len(closes) - 1) + [80.0]
        reading = detect_pump(closes, volumes)
        self.assertGreaterEqual(reading.price_change_15m or 0, 5)
        self.assertLess(reading.price_change_5m or 0, 3)
        self.assertGreaterEqual(reading.rsi or 0, 60)
        self.assertLessEqual(reading.rsi or 100, 85)
        self.assertGreaterEqual(reading.volume_ratio or 0, 5)
        self.assertTrue(reading.matched)

    def test_rsi_above_zone_rejects(self) -> None:
        price = 100.0
        closes: list[float] = []
        for index in range(40):
            price *= 1.003 if index % 3 else 0.998
            closes.append(price)
        base = closes[24]
        closes = closes[:25]
        for index in range(1, 16):
            closes.append(base * (1 + 0.055 * index / 15))
        volumes = [10.0] * (len(closes) - 1) + [80.0]
        reading = detect_pump(closes, volumes)
        self.assertGreater(reading.rsi or 0, 85)
        self.assertFalse(reading.matched)

    def test_quiet_volume_rejects(self) -> None:
        closes = _pump_closes()
        volumes = [10.0] * len(closes)
        self.assertFalse(detect_pump(closes, volumes).matched)

    def test_price_change_windows(self) -> None:
        closes = [100.0] * 16
        closes[-1] = 103
        self.assertAlmostEqual(price_change_pct(closes, 5) or 0, 3.0, places=4)
        self.assertAlmostEqual(price_change_pct(closes, 15) or 0, 3.0, places=4)


class LiquidationTest(unittest.TestCase):
    def test_fade_from_peak(self) -> None:
        self.assertTrue(liquidations_faded([0, 100, 30]))
        self.assertFalse(liquidations_faded([0, 100, 50]))
        self.assertFalse(liquidations_faded([0, 0, 0]))

    def test_buy_side_is_not_a_short_liquidation(self) -> None:
        self.assertTrue(is_short_liquidation("Sell"))
        self.assertFalse(is_short_liquidation("Buy"))

    def test_window_includes_empty_minutes(self) -> None:
        now = START + 5 * 60_000
        buckets = {START: 80.0, now: 10.0}
        values = window_notionals(buckets, now, minutes=6)
        self.assertEqual(len(values), 6)
        self.assertEqual(values[0], 80.0)
        self.assertEqual(values[-1], 10.0)
        self.assertTrue(liquidations_faded(values))


class FlowTest(unittest.TestCase):
    def test_oi_drop(self) -> None:
        start = START
        later = start + 30 * 60_000
        self.assertTrue(oi_falling([(start, 100.0), (later, 99.0)]))
        self.assertFalse(oi_falling([(start, 100.0), (later, 101.0)]))

    def test_volume_returns_to_average(self) -> None:
        volumes = [10.0] * 20 + [100.0, 10.0, 8.0]
        self.assertTrue(volume_faded(volumes))
        self.assertFalse(volume_faded([10.0] * 20 + [100.0, 100.0]))

    def test_cvd_and_taker_and_funding(self) -> None:
        now = START + 10 * 60_000
        cvd = {now: -5.0}
        self.assertTrue(cvd_bearish(cvd, 6.0, now))
        self.assertFalse(cvd_bearish(cvd, -1.0, now))
        buy = {now: 10.0}
        sell = {now: 20.0}
        self.assertAlmostEqual(taker_ratio(buy, sell, now) or 0, 0.5)
        self.assertTrue(funding_extreme(0.001))
        self.assertFalse(funding_extreme(0.0001))

    def test_obv_divergence(self) -> None:
        closes = [100.0]
        volumes = [1.0]
        for index in range(20):
            if index % 2 == 0:
                closes.append(closes[-1] + 1)
                volumes.append(1)
            else:
                closes.append(closes[-1] - 0.4)
                volumes.append(10)
        self.assertTrue(obv_bearish(closes, volumes, 1.0))


class LevelTest(unittest.TestCase):
    def test_score_and_class(self) -> None:
        # (2 × 3) + (1 × 2) + (3 × 1) − (1 × 5) = 6 → средний, пока уровень не пробит последним.
        self.assertEqual(level_score(2, 1, 3, 1), 6)
        self.assertEqual(classify_level(6, "sweep"), "medium")
        self.assertEqual(classify_level(8, "touch"), "strong")
        self.assertEqual(classify_level(6, "break"), "broken")
        self.assertEqual(classify_level(0, "touch"), "broken")

    def test_sweep_after_confirmed_pivot(self) -> None:
        candles = []
        for index in range(11):
            high = 12.0 if index == 5 else 10.0
            candles.append(Candle(index * HOUR, 10, high, 9, 10, 1))
        candles.append(Candle(11 * HOUR, 12, 13, 10, 11, 1))
        pivots = find_pivot_highs(candles[:-1])
        self.assertIn(12.0, pivots)
        swept, levels, candle = sweep_on_timeframe(candles, 100 * HOUR, HOUR)
        self.assertTrue(swept)
        assert candle is not None
        self.assertTrue(any(candle_swept_level(candle, level) for level in levels))
        scored = score_level(candles[:-1], 12.0)
        self.assertNotEqual(scored.kind, "broken")

    def test_round_step_and_two_pierces(self) -> None:
        self.assertAlmostEqual(round_step(16500), 1000)
        self.assertAlmostEqual(round_step(0.025), 0.001)
        pierced = Candle(0, 1.2, 1.25, 1.1, 1.15, 1)
        quiet = Candle(60_000, 1.16, 1.18, 1.14, 1.17, 1)
        self.assertTrue(round_level_confirmed([pierced, quiet, pierced]))
        self.assertFalse(round_level_confirmed([pierced]))


class RatingTest(unittest.TestCase):
    def test_formula(self) -> None:
        # 3×20 + 70×0.5 + 2×10 + 2×5 + 1×3 = 128
        self.assertEqual(signal_rating(3, 70, 2, 2, 1), 128)

    def test_expert_prior_and_history(self) -> None:
        prior = expert_probability(
            sweep=True,
            liquidations_faded=True,
            oi_drop=False,
            cvd_divergence=False,
            round_level=False,
            funding_extreme=False,
        )
        self.assertEqual(prior, 85)
        historical = probability_pct(
            sweep=False,
            liquidations_faded=False,
            oi_drop=False,
            cvd_divergence=False,
            round_level=False,
            funding_extreme=False,
            history_wins=10,
            history_total=20,
        )
        self.assertEqual(historical, 50)
        self.assertEqual(column_for(5)["status"], "ВХОД")
        self.assertEqual(column_for(1)["color"], "gray")

    def test_sort_and_strength(self) -> None:
        ordered = sort_by_rating([type("S", (), {"rating": 1})(), type("S", (), {"rating": 9})()])
        self.assertEqual([item.rating for item in ordered], [9, 1])
        reading = Reading(pump=True, liquidations_faded=True, oi_drop=True, cvd_divergence=True)
        self.assertEqual(reading.strength(True), 3)
        self.assertEqual(reading.extra_count(), 1)


class OutcomeTest(unittest.TestCase):
    def test_targets(self) -> None:
        entry = 100.0
        created = START
        self.assertEqual(classify_outcome(entry, 96.9, created, created + 1000), "TP_HIT")
        self.assertEqual(classify_outcome(entry, 110, created, created + 1000), "LIQUIDATED")
        self.assertEqual(classify_outcome(entry, 100, created, created + 24 * HOUR), "TIME_EXIT")
        self.assertIsNone(classify_outcome(entry, 100, created, created + 1000))
        self.assertAlmostEqual(short_pnl_pct(100, 96) or 0, 40)
        self.assertAlmostEqual(short_pnl_pct(100, 110) or 0, -100)


class EngineTest(unittest.TestCase):
    def test_open_update_and_take_profit(self) -> None:
        closes = _pump_closes()
        volumes = [10.0] * (len(closes) - 1) + [80.0]
        now = START + (len(closes) - 1) * 60_000
        with tempfile.TemporaryDirectory() as folder:
            engine, store = _engine(folder)
            engine.ingest(_klines("BEAMUSDT", closes, volumes))
            opened = engine.scan(now)
            signal_messages = [item for item in opened if item["type"] == "signal"]
            self.assertEqual(signal_messages[0]["data"]["event"], "open")
            self.assertEqual(signal_messages[0]["data"]["label"], "1/5")
            self.assertEqual(signal_messages[0]["data"]["checks"]["pump"], True)
            board = [item for item in opened if item["type"] == "board"][0]
            self.assertEqual(board["data"]["columns"][0]["strength"], 5)
            self.assertEqual(len(board["data"]["columns"][-1]["signals"]), 1)

            engine.ingest(
                {
                    "symbol": "BEAMUSDT",
                    "timestamp": now - 60_000,
                    "type": "liquidation",
                    "data": {"side": "Sell", "price": 10, "size": 10},
                }
            )
            engine.ingest(
                {
                    "symbol": "BEAMUSDT",
                    "timestamp": now,
                    "type": "liquidation",
                    "data": {"side": "Sell", "price": 1, "size": 10},
                }
            )
            # Лонговые ликвидации топливо шортового пампа не считают.
            engine.ingest(
                {
                    "symbol": "BEAMUSDT",
                    "timestamp": now,
                    "type": "liquidation",
                    "data": {"side": "Buy", "price": 10, "size": 100},
                }
            )
            updated = engine.scan(now + 1000)
            update = [item for item in updated if item["type"] == "signal"][0]
            self.assertEqual(update["data"]["event"], "update")
            self.assertEqual(update["data"]["strength"], 2)
            self.assertEqual(update["data"]["status"], "ФОРМИРОВАНИЕ")
            self.assertTrue(update["data"]["checks"]["liquidations_faded"])

            entry = update["data"]["entry_price"]
            engine.ingest(
                {
                    "symbol": "BEAMUSDT",
                    "timestamp": now + 120_000,
                    "type": "trade",
                    "data": {"price": entry * 0.96, "size": 1, "side": "Sell"},
                }
            )
            closed = engine.scan(now + 130_000)
            close = [item for item in closed if item["type"] == "signal"][0]
            self.assertEqual(close["data"]["outcome"], "TP_HIT")
            self.assertAlmostEqual(close["data"]["pnl_pct"], 40)
            self.assertEqual(store.load_open(), [])
            wins, total = store.outcome_counts()
            self.assertEqual((wins, total), (1, 1))
            store.close()

    def test_liquidation_and_time_exit(self) -> None:
        closes = _pump_closes()
        volumes = [10.0] * (len(closes) - 1) + [80.0]
        now = START + (len(closes) - 1) * 60_000
        with tempfile.TemporaryDirectory() as folder:
            engine, store = _engine(folder)
            engine.ingest(_klines("AAAUSDT", closes, volumes))
            opened = engine.scan(now)
            entry = [item for item in opened if item["type"] == "signal"][0]["data"]["entry_price"]
            engine.ingest(
                {
                    "symbol": "AAAUSDT",
                    "timestamp": now + 60_000,
                    "type": "trade",
                    "data": {"price": entry * 1.1, "size": 1, "side": "Buy"},
                }
            )
            closed = engine.scan(now + 60_000)
            outcome = [item for item in closed if item["type"] == "signal"][0]["data"]["outcome"]
            self.assertEqual(outcome, "LIQUIDATED")

            engine.ingest(_klines("BBBUSDT", closes, volumes))
            opened = engine.scan(now)
            created = [item for item in opened if item["data"].get("symbol") == "BBBUSDT"][0]
            self.assertEqual(created["data"]["event"], "open")
            later = engine.scan(created["data"]["created_at"] + 24 * HOUR)
            time_exit = [
                item
                for item in later
                if item["type"] == "signal" and item["data"]["symbol"] == "BBBUSDT"
            ][0]
            self.assertEqual(time_exit["data"]["outcome"], "TIME_EXIT")
            store.close()

    def test_state_ignores_buy_liquidation_notional(self) -> None:
        state = SymbolState("BEAMUSDT")
        state.ingest(
            {
                "symbol": "BEAMUSDT",
                "timestamp": START,
                "type": "liquidation",
                "data": {"side": "Buy", "price": 2, "size": 5},
            }
        )
        self.assertEqual(state.liq_notional, {})


if __name__ == "__main__":
    unittest.main()
