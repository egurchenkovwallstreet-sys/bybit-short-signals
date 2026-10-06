"""Поиск пампов: длинный рост от минимума до максимума."""

from __future__ import annotations

import unittest

import config
from signal_engine.pump_strategy import detect_long_pump, format_period_ru
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
        for i in range(25):
            ts = now - (25 - i) * 86_400_000
            if i < 5:
                low, high = 10.0, 10.5
            elif i < 15:
                low, high = 10.0, 12.0 + i * 0.5
            else:
                low, high = 17.0, 19.0
            bars.append(_bar(ts, low, high))
        state.bars_htf["D"] = bars
        match = detect_long_pump(state, now)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertGreaterEqual(match.growth_pct, 80.0)
        self.assertEqual(match.kind, "long")

    def test_turnover_blocks(self) -> None:
        state = SymbolState("LOWUSDT")
        state.turnover_24h_usdt = 100_000
        now = 1_800_000_000_000
        state.bars_htf["D"] = [_bar(now - 86_400_000, 1.0, 5.0)]
        self.assertIsNone(detect_long_pump(state, now))

    def test_format_period(self) -> None:
        self.assertEqual(format_period_ru(0, 3_600_000), "1 ч")
        self.assertEqual(format_period_ru(0, 3 * 86_400_000), "3 д")


if __name__ == "__main__":
    unittest.main()
