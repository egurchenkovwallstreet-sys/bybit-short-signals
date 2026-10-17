# -*- coding: utf-8 -*-
"""БАБЛОСОС $$$: M5 LH pivot, стоп от свечи pivot."""

from __future__ import annotations

import unittest

import config
from signal_engine.paper.lh_scan_pivot import signal_from_pivot_diff
from signal_engine.paper.pivot_clock import (
    batch_has_closed_bar,
    first_bar_waiting,
    just_confirmed,
    second_bar_close_ms,
    symbols_waiting_second_bar,
)
from signal_engine.paper.position import Position, bab_pivot_stop_price, price_for_roe
from signal_engine.paper.pyl_detect import PYL_MANDATORY, evaluate_pyl
from signal_engine.paper.vac_lh_detect import (
    detect_entry_signal,
    entry_open_until_ms,
    evaluate_vps,
)
from signal_engine.state import Bar, SymbolState

STEP = 300_000
T0 = 1_700_000_000_000


def _state_with_5m_peak() -> tuple[SymbolState, int, int]:
    bars: list[Bar] = []
    for i in range(30):
        ts = T0 + i * STEP
        bars.append(Bar(ts, 10.0, 10.2, 9.8, 10.0, 1.0))
    peak_ts = T0 + 30 * STEP
    bars.append(Bar(peak_ts, 10.0, 15.0, 9.9, 12.0, 1.0))
    for i in range(31, 80):
        ts = T0 + i * STEP
        bars.append(Bar(ts, 10.0, 10.3, 9.7, 10.0, 1.0))
    now_ms = bars[-1].timestamp + STEP
    state = SymbolState("XUSDT", last_price=10.0, turnover_24h_usdt=2_000_000.0)
    state.bars_htf["5"] = bars
    return state, now_ms, peak_ts


class BabStopTest(unittest.TestCase):
    def test_short_stop_above_pivot_high_by_5_roe(self) -> None:
        high = 100.0
        low = 98.0
        stop = bab_pivot_stop_price("short", high, low, leverage=10)
        self.assertAlmostEqual(stop, price_for_roe(high, -config.PAPER_PYL_STOP_ROE, 10))

    def test_long_stop_below_pivot_low_by_5_roe(self) -> None:
        high = 102.0
        low = 100.0
        stop = bab_pivot_stop_price("long", high, low, leverage=10)
        self.assertLess(stop, low)


class PylPivotDiffTest(unittest.TestCase):
    def test_new_peak_is_short_signal(self) -> None:
        prev = {"peaks": [], "troughs": []}
        cur = {"peaks": [{"time_ms": 1_000_000, "price": 10.0}], "troughs": []}
        sig = signal_from_pivot_diff(prev, cur)
        assert sig is not None
        self.assertEqual(sig["side"], "short")

    def test_first_snap_none_prev_is_short(self) -> None:
        cur = {"peaks": [{"time_ms": 1_000_000, "price": 10.0}], "troughs": []}
        sig = signal_from_pivot_diff(None, cur)
        assert sig is not None
        self.assertEqual(sig["side"], "short")

    def test_mandatory_count(self) -> None:
        self.assertEqual(len(PYL_MANDATORY), 4)


class FiveMinStoreAndEntryTest(unittest.TestCase):
    def test_engine_stores_5m_klines(self) -> None:
        state = SymbolState("XUSDT")
        candles = [
            {
                "timestamp": T0 + i * STEP,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "volume": 2.0,
            }
            for i in range(6)
        ]
        state.ingest(
            {
                "type": "kline",
                "symbol": "XUSDT",
                "timestamp": T0,
                "data": {"interval": "5", "candles": candles},
            }
        )
        self.assertEqual(len(state.bars_htf.get("5") or []), 6)

    def test_vps5_enters_like_pyl_without_window(self) -> None:
        state, now_ms, peak_ts = _state_with_5m_peak()
        pyl = evaluate_pyl(state, now_ms, None)
        self.assertTrue(pyl["passed"], pyl.get("failed"))
        self.assertEqual(pyl.get("side"), "short")
        late = entry_open_until_ms(peak_ts, "5") + 10 * STEP
        window_sig = detect_entry_signal(None, pyl["metrics"], "5", late)
        self.assertIsNone(window_sig)
        vps15_style = evaluate_vps(state, late, None, "5", kind="vps5")
        self.assertFalse(vps15_style["passed"])
        self.assertIn("entry_window", vps15_style["failed"])
        pyl_late = evaluate_pyl(state, late, None)
        self.assertTrue(pyl_late["passed"], pyl_late.get("failed"))

    def test_collector_fetches_5m(self) -> None:
        self.assertIn("5", config.KLINE_INTERVALS)


class PivotConfirmClockTest(unittest.TestCase):
    def test_window_is_ten_seconds_after_second_bar(self) -> None:
        pivot = T0
        close_at = second_bar_close_ms(pivot, "5")
        self.assertEqual(close_at, pivot + 3 * STEP)
        self.assertTrue(just_confirmed(pivot, close_at, "5"))
        self.assertTrue(just_confirmed(pivot, close_at + 9_000, "5"))
        self.assertFalse(just_confirmed(pivot, close_at + 11_000, "5"))
        self.assertFalse(just_confirmed(pivot, close_at - 1, "5"))
        self.assertTrue(first_bar_waiting(pivot, close_at - 1_000, "5"))
        self.assertFalse(first_bar_waiting(pivot, close_at, "5"))

    def test_waiting_symbol_is_armed_after_first_bar(self) -> None:
        bars: list[Bar] = []
        for i in range(50):
            bars.append(Bar(T0 + i * STEP, 10.0, 10.2, 9.8, 10.0, 1.0))
        peak_ts = T0 + 50 * STEP
        bars.append(Bar(peak_ts, 10.0, 15.0, 9.9, 12.0, 1.0))
        bars.append(Bar(peak_ts + STEP, 10.0, 10.3, 9.7, 10.0, 1.0))
        now_ms = peak_ts + 2 * STEP + 1_000
        state = SymbolState("XUSDT", last_price=10.0, turnover_24h_usdt=2_000_000.0)
        state.bars_htf["5"] = bars
        armed = symbols_waiting_second_bar({"XUSDT": state}, now_ms, "5")
        self.assertIn("XUSDT", armed)
        self.assertFalse(just_confirmed(peak_ts, now_ms, "5"))
        self.assertTrue(just_confirmed(peak_ts, second_bar_close_ms(peak_ts, "5") + 500, "5"))

    def test_closed_bar_ready_when_next_candle_exists(self) -> None:
        close_ms = T0 + 3 * STEP
        candles = [{"timestamp": close_ms - STEP}, {"timestamp": close_ms}]
        self.assertTrue(batch_has_closed_bar(candles, close_ms, close_ms + 700))
        self.assertFalse(batch_has_closed_bar([{"timestamp": close_ms - 2 * STEP}], close_ms, close_ms + 700))

    def test_opposite_close_uses_market_not_stop(self) -> None:
        pos = Position(
            symbol="XUSDT",
            opened_at=T0,
            entry_price=100.0,
            margin=50.0,
            side="long",
            stop_style="bab",
            stop_price=90.0,
            last_price=101.5,
        )
        market = pos.close_result("opposite_pivot")
        stopped = pos.close_result("trailing_stop")
        self.assertAlmostEqual(market["exit_price"], 101.5)
        self.assertAlmostEqual(stopped["exit_price"], 90.0)


if __name__ == "__main__":
    unittest.main()
