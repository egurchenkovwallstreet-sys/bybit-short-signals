"""Единый детект пампа."""

from __future__ import annotations

import unittest

import config
from signal_engine.pump_unified import detect_unified_episodes, meets_unified_turnover, min_growth_pct
from signal_engine.state import Bar, SymbolState


class PumpUnifiedTests(unittest.TestCase):
    def test_thresholds_match_lab_defaults(self) -> None:
        self.assertEqual(min_growth_pct("fast"), 40.0)
        self.assertEqual(min_growth_pct("long"), 100.0)

    def test_turnover(self) -> None:
        state = SymbolState("A")
        state.turnover_24h_usdt = config.PUMP_UNIFIED_MIN_TURNOVER_USDT - 1
        self.assertFalse(meets_unified_turnover(state))
        state.turnover_24h_usdt = config.PUMP_UNIFIED_MIN_TURNOVER_USDT
        self.assertTrue(meets_unified_turnover(state))

    def test_24h_ticker_path(self) -> None:
        now_ms = 1_700_000_000_000
        state = SymbolState("TUSDT", last_price=135.0)
        state.turnover_24h_usdt = config.PUMP_UNIFIED_MIN_TURNOVER_USDT
        state.price_24h_change = 0.36
        step = 15 * 60_000
        for i in range(96):
            ts = now_ms - (95 - i) * step
            low = 100.0 if i < 10 else 100.0 + (i - 10) * 0.45
            high = low + 2.0
            state.bars_htf.setdefault("15", []).append(
                Bar(ts, low, high, low, low + 1.0, 10_000.0)
            )
        episodes = detect_unified_episodes(state, now_ms)
        self.assertTrue(episodes)
        self.assertTrue(any(e.source == "ticker_24h" for e in episodes))


if __name__ == "__main__":
    unittest.main()
