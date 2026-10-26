"""Единый детект пампа: 1ч / 4ч / сутки."""

from __future__ import annotations

import unittest

import config
from signal_engine.pump_unified import (
    detect_unified_episodes,
    meets_unified_turnover,
    min_growth_pct,
    min_volume_ratio,
    should_remove_after_peak_drawdown,
)
from signal_engine.state import Bar, SymbolState

HOUR = 3_600_000
H4 = 4 * HOUR


def _bars(now_ms: int, n: int, step: int, last_low: float, last_high: float, last_vol: float) -> list[Bar]:
    out: list[Bar] = []
    for i in range(n):
        ts = now_ms - (n - i) * step
        if i == n - 1:
            out.append(Bar(ts, last_low, last_high, last_low, last_high * 0.98, last_vol))
        else:
            out.append(Bar(ts, 100.0, 101.0, 100.0, 100.5, 100.0))
    return out


def _state(symbol: str, now_ms: int, bars_1h: list[Bar] | None = None) -> SymbolState:
    state = SymbolState(symbol, last_price=120.0)
    state.turnover_24h_usdt = config.PUMP_UNIFIED_MIN_TURNOVER_USDT
    if bars_1h:
        state.bars_htf["60"] = bars_1h
        state.last_price = bars_1h[-1].close
    return state


class PumpUnifiedTests(unittest.TestCase):
    def test_thresholds(self) -> None:
        self.assertEqual(min_growth_pct("fast"), 20.0)
        self.assertEqual(min_growth_pct("medium"), 40.0)
        self.assertEqual(min_growth_pct("long"), 60.0)
        self.assertEqual(min_volume_ratio("fast"), 3.0)
        self.assertEqual(min_volume_ratio("medium"), 5.0)
        self.assertEqual(min_volume_ratio("long"), 8.0)

    def test_remove_at_50pct_drawdown(self) -> None:
        state = SymbolState("X", last_price=51.0)
        self.assertFalse(should_remove_after_peak_drawdown(state, 100.0))
        state.last_price = 50.0
        self.assertTrue(should_remove_after_peak_drawdown(state, 100.0))

    def test_turnover(self) -> None:
        state = SymbolState("A")
        state.turnover_24h_usdt = config.PUMP_UNIFIED_MIN_TURNOVER_USDT - 1
        self.assertFalse(meets_unified_turnover(state))
        state.turnover_24h_usdt = config.PUMP_UNIFIED_MIN_TURNOVER_USDT
        self.assertTrue(meets_unified_turnover(state))

    def test_fast_1h_growth_and_volume(self) -> None:
        now_ms = 1_700_500_000_000
        state = _state("FASTUSDT", now_ms, _bars(now_ms, 30, HOUR, 100.0, 125.0, 400.0))
        episodes = detect_unified_episodes(state, now_ms)
        fast = [e for e in episodes if e.pump_class == "fast"]
        self.assertTrue(fast)
        self.assertGreaterEqual(fast[0].growth_pct, 20.0)
        self.assertGreaterEqual(fast[0].volume_ratio or 0, 3.0)
        self.assertAlmostEqual(fast[0].peak_price, 125.0)
        self.assertTrue(fast[0].source.startswith("htf_"))

    def test_reject_small_1h_move(self) -> None:
        now_ms = 1_700_500_000_000
        state = _state("WEAKUSDT", now_ms, _bars(now_ms, 30, HOUR, 100.0, 115.0, 400.0))
        episodes = detect_unified_episodes(state, now_ms)
        self.assertFalse(any(e.pump_class == "fast" for e in episodes))

    def test_reject_low_volume(self) -> None:
        now_ms = 1_700_500_000_000
        state = _state("DRYUSDT", now_ms, _bars(now_ms, 30, HOUR, 100.0, 125.0, 150.0))
        episodes = detect_unified_episodes(state, now_ms)
        self.assertFalse(any(e.pump_class == "fast" for e in episodes))

    def test_medium_4h(self) -> None:
        now_ms = 1_700_500_000_000
        state = _state("MIDUSDT", now_ms)
        state.bars_htf["240"] = _bars(now_ms, 36, H4, 100.0, 145.0, 600.0)
        state.last_price = 140.0
        episodes = detect_unified_episodes(state, now_ms)
        mid = [e for e in episodes if e.pump_class == "medium"]
        self.assertTrue(mid)
        self.assertGreaterEqual(mid[0].growth_pct, 40.0)
        self.assertGreaterEqual(mid[0].volume_ratio or 0, 5.0)

    def test_30d_levels_on_draft(self) -> None:
        now_ms = 1_700_500_000_000
        state = _state("LVLUSDT", now_ms, _bars(now_ms, 30, HOUR, 100.0, 125.0, 400.0))
        state.bars_htf["240"] = [
            Bar(now_ms - 10 * H4, 80.0, 90.0, 70.0, 85.0, 100.0),
            Bar(now_ms - H4, 100.0, 200.0, 95.0, 150.0, 100.0),
        ]
        state.bars_htf["D"] = [
            Bar(now_ms - 3 * 24 * HOUR, 60.0, 70.0, 50.0, 65.0, 100.0),
            Bar(now_ms - 24 * HOUR, 90.0, 180.0, 88.0, 120.0, 100.0),
        ]
        episodes = detect_unified_episodes(state, now_ms)
        self.assertTrue(episodes)
        draft = episodes[0]
        self.assertAlmostEqual(draft.h4_high or 0, 200.0)
        self.assertAlmostEqual(draft.h4_low or 0, 70.0)
        self.assertAlmostEqual(draft.d1_high or 0, 180.0)
        self.assertAlmostEqual(draft.d1_low or 0, 50.0)


if __name__ == "__main__":
    unittest.main()
