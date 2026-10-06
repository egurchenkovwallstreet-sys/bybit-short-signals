"""Поиск пампов: длинный рост от минимума до максимума."""

from __future__ import annotations

import unittest

import config
from signal_engine.pump_strategy import detect_long_pump, detect_short_pump, format_period_ru
from signal_engine.state import Bar, SymbolState


def _bar(ts: int, low: float, high: float, close: float | None = None) -> Bar:
    c = close if close is not None else (low + high) / 2
    return Bar(ts, low, high, low, c, 1.0, from_kline=True)


class PumpStrategyTests(unittest.TestCase):
    def test_detect_long_pump_daily(self) -> None:
        state = SymbolState("TESTUSDT")
        state.turnover_24h_usdt = config.PUMP_STRATEGY_MIN_TURNOVER_24H_USDT + 1
        state.last_price = 18.0
        now = 1_800_000_000_000
        bars = []
        for i in range(12):
            ts = now - (12 - i) * 86_400_000
            if i < 3:
                low, high = 10.0, 10.5
            elif i < 8:
                low, high = 10.0, 12.0 + i * 1.5
            else:
                low, high = 18.0, 21.0
            bars.append(_bar(ts, low, high))
        state.bars_htf["D"] = bars
        match = detect_long_pump(state, now)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertGreaterEqual(match.peak_price / match.valley_price, config.PUMP_STRATEGY_LONG_MIN_MULTIPLIER)
        self.assertEqual(match.kind, "long")

    def test_long_pump_peak_before_pullback(self) -> None:
        """Пик был раньше, сейчас откат — всё равно считаем min/max в окне."""
        state = SymbolState("PULLUSDT")
        state.turnover_24h_usdt = config.PUMP_STRATEGY_MIN_TURNOVER_24H_USDT + 1
        state.last_price = 8.0
        now = 2_100_000_000_000
        bars = []
        for i in range(10):
            ts = now - (10 - i) * 86_400_000
            if i < 5:
                low, high = 10.0, 22.0
            else:
                low, high = 8.0, 9.0
            bars.append(_bar(ts, low, high))
        state.bars_htf["D"] = bars
        match = detect_long_pump(state, now)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertGreaterEqual(match.peak_price, 20.0)
        self.assertLessEqual(match.valley_price, 10.0)

    def test_turnover_blocks(self) -> None:
        state = SymbolState("LOWUSDT")
        state.turnover_24h_usdt = 100_000
        now = 1_800_000_000_000
        state.bars_htf["D"] = [_bar(now - 86_400_000, 1.0, 5.0)]
        self.assertIsNone(detect_long_pump(state, now))

    def test_detect_short_pump_5m(self) -> None:
        state = SymbolState("FASTUSDT")
        state.turnover_24h_usdt = config.PUMP_STRATEGY_MIN_TURNOVER_24H_USDT + 1
        state.last_price = 14.0
        now = 2_000_000_000_000
        bars = []
        step = 300_000
        for i in range(80):
            ts = now - (80 - i) * step
            if i < 40:
                low, high = 10.0, 10.2
            elif i < 55:
                low, high = 10.0, 10.0 + (i - 40) * 0.35
            else:
                low, high = 13.5, 14.5
            bars.append(_bar(ts, low, high))
        state.bars_htf["5"] = bars
        match = detect_short_pump(state, now)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.kind, "short")
        self.assertGreaterEqual(match.growth_pct, 40.0)
        hours = (match.peak_ts - match.valley_ts) / 3_600_000
        self.assertGreaterEqual(hours, config.PUMP_STRATEGY_SHORT_HOURS_MIN)
        self.assertLessEqual(hours, config.PUMP_STRATEGY_SHORT_HOURS_MAX)

    def test_format_period(self) -> None:
        self.assertEqual(format_period_ru(0, 3_600_000), "1 ч")
        self.assertEqual(format_period_ru(0, 3 * 86_400_000), "3 д")


if __name__ == "__main__":
    unittest.main()
