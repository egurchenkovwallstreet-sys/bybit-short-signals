# -*- coding: utf-8 -*-
"""БАБЛОСОС $$$: M5 LH pivot, стоп от свечи pivot."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import config
from signal_engine.paper.lh_scan_pivot import signal_from_pivot_diff
from signal_engine.paper.pivot_clock import (
    batch_has_closed_bar,
    entry_on_third_bar,
    first_bar_waiting,
    just_confirmed,
    second_bar_close_ms,
    symbols_waiting_second_bar,
    third_bar_close_ms,
    third_bar_open_ms,
)
from signal_engine.paper.position import Position, bab_pivot_stop_price, price_for_roe
from signal_engine.paper.m5_htf import (
    htf_pivot_setup,
    htf_second_bar_pending,
    m5_htf_setup,
    opposite_anchor_pivot_exit,
    opposite_appeared,
    opposite_pivot_exit_signal,
    qualify_m5_pivot,
)
from signal_engine.paper.pyl_detect import (
    PYL_MANDATORY,
    evaluate_htf_pivot_entry,
    evaluate_pyl,
    pyl1_range_expanding,
    pyl1_structure_allows_entry,
    structure_bias_two_pivots,
)
from signal_engine.swing_highs import closed_bars
from signal_engine.paper.vac_lh_detect import detect_entry_signal, entry_open_until_ms
from signal_engine.state import Bar, SymbolState

STEP = 300_000
T0 = 1_700_000_000_000


def _aligned_base() -> int:
    raw = 1_700_000_000_000
    return raw - (raw % (6 * STEP))


def _bars(base: int, highs: list[float], lows: list[float]) -> list[Bar]:
    out: list[Bar] = []
    for i, (high, low) in enumerate(zip(highs, lows)):
        mid = (high + low) / 2
        out.append(Bar(base + i * STEP, mid, high, low, mid, 1.0))
    return out


def _lower_high_state() -> tuple[SymbolState, int, int]:
    """Предыдущая 30м high 16, предыдущая 15м high 14, экстремум 12 на первой 5м своей 15м."""
    base = _aligned_base()
    highs = [16, 15, 14.5, 13, 12.5, 14, 13, 12.2, 11.5, 12, 11, 11, 10.5]
    lows = [9] * len(highs)
    bars = _bars(base, highs, lows)
    peak_ts = base + 9 * STEP
    now_ms = peak_ts + 3 * STEP + 60_000
    state = SymbolState("XUSDT", last_price=11.0, turnover_24h_usdt=2_000_000.0)
    state.bars_htf["5"] = bars
    return state, now_ms, peak_ts


class Pyl1StructureTest(unittest.TestCase):
    def test_structure_bias_up_down_mixed(self) -> None:
        peaks_up = [{"price": 10.0}, {"price": 11.0}]
        troughs_up = [{"price": 8.0}, {"price": 9.0}]
        self.assertEqual(structure_bias_two_pivots(peaks_up, troughs_up), "up")
        peaks_down = [{"price": 11.0}, {"price": 10.0}]
        troughs_down = [{"price": 9.0}, {"price": 8.0}]
        self.assertEqual(structure_bias_two_pivots(peaks_down, troughs_down), "down")
        self.assertEqual(structure_bias_two_pivots(peaks_up, troughs_down), "mixed")

    def test_pyl1_range_expanding(self) -> None:
        peaks = [{"price": 10.0}, {"price": 11.0}]
        troughs = [{"price": 9.0}, {"price": 8.0}]
        self.assertTrue(pyl1_range_expanding(peaks, troughs))
        self.assertFalse(pyl1_range_expanding([{"price": 11.0}, {"price": 10.0}], troughs))
        self.assertFalse(pyl1_range_expanding(peaks, [{"price": 8.0}, {"price": 9.0}]))

    def test_pyl1_structure_allows_contracting(self) -> None:
        peaks = [{"price": 11.0}, {"price": 10.0}]
        troughs = [{"price": 8.0}, {"price": 9.0}]
        self.assertTrue(pyl1_structure_allows_entry("short", peaks, troughs))
        self.assertTrue(pyl1_structure_allows_entry("long", peaks, troughs))
        expanding_peaks = [{"price": 10.0}, {"price": 11.0}]
        expanding_troughs = [{"price": 9.0}, {"price": 8.0}]
        self.assertFalse(pyl1_structure_allows_entry("long", expanding_peaks, expanding_troughs))
        self.assertFalse(
            pyl1_structure_allows_entry("short", [{"price": 11.0}, {"price": 12.0}], troughs)
        )


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
        self.assertEqual(len(PYL_MANDATORY), 3)


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
        state, now_ms, peak_ts = _lower_high_state()
        snap = {
            "interval": "5",
            "peaks": [{"time_ms": peak_ts, "price": 12.0, "left_strength": 30}],
            "troughs": [],
        }
        with patch("signal_engine.paper.m5_htf.snapshot_pivot_levels", return_value=snap):
            pyl = evaluate_pyl(state, now_ms, None)
            self.assertTrue(pyl["passed"], pyl.get("failed"))
            self.assertEqual(pyl.get("side"), "short")
            self.assertEqual(pyl["metrics"]["pivot_time_ms"], peak_ts)
            self.assertTrue(entry_on_third_bar(peak_ts, now_ms, "5"))
            late = third_bar_close_ms(peak_ts, "5") + 10 * STEP
            self.assertFalse(entry_on_third_bar(peak_ts, late, "5"))
            window_sig = detect_entry_signal(None, pyl["metrics"], "5", late)
            self.assertIsNone(window_sig)
            vps5_late = evaluate_htf_pivot_entry(state, late, None, "5", kind="vps5")
            self.assertFalse(vps5_late["passed"])
            pyl_late = evaluate_pyl(state, late, None)
            self.assertFalse(pyl_late["passed"])

    def test_collector_fetches_5m(self) -> None:
        self.assertIn("5", config.KLINE_INTERVALS)


class M5HtfGateTest(unittest.TestCase):
    def test_pyl_ignores_htf_uses_left_strength(self) -> None:
        base = _aligned_base()
        highs = [16, 15, 14.5, 13, 12.5, 14, 10, 10, 10, 12, 11, 11, 10.5]
        bars = _bars(base, highs, [9] * len(highs))
        state = SymbolState("XUSDT", last_price=11.0, turnover_24h_usdt=2_000_000.0)
        state.bars_htf["5"] = bars
        peak_ts = base + 9 * STEP
        now_ms = peak_ts + 3 * STEP + 60_000
        index = {int(b.timestamp): b for b in closed_bars(bars, "5", now_ms)}
        self.assertEqual(qualify_m5_pivot(index, peak_ts, "short"), "not_weaker_15m")
        snap = {
            "interval": "5",
            "peaks": [{"time_ms": peak_ts, "price": 12.0, "left_strength": 30}],
            "troughs": [],
        }
        with patch("signal_engine.paper.m5_htf.snapshot_pivot_levels", return_value=snap):
            pyl = evaluate_pyl(state, now_ms, None)
        self.assertTrue(pyl["passed"], pyl.get("failed"))
        self.assertEqual(pyl["metrics"].get("left_strength"), 30)

    def test_break_of_prior_30m_is_rejected(self) -> None:
        base = _aligned_base()
        highs = [11, 10.5, 10, 10, 10, 10, 14, 13, 12.5, 12, 11, 11]
        bars = _bars(base, highs, [9] * len(highs))
        state = SymbolState("XUSDT", last_price=11.0, turnover_24h_usdt=2_000_000.0)
        state.bars_htf["5"] = bars
        peak_ts = base + 9 * STEP
        now_ms = peak_ts + 3 * STEP + 60_000
        index = {int(b.timestamp): b for b in closed_bars(bars, "5", now_ms)}
        self.assertEqual(qualify_m5_pivot(index, peak_ts, "short"), "break_30m")
        snap = {
            "interval": "5",
            "peaks": [{"time_ms": peak_ts, "price": 12.0, "left_strength": 30}],
            "troughs": [],
        }
        with patch("signal_engine.paper.m5_htf.snapshot_pivot_levels", return_value=snap):
            pyl = evaluate_pyl(state, now_ms, None)
            setup = m5_htf_setup(state, now_ms)
        self.assertTrue(pyl["passed"], pyl.get("failed"))
        self.assertIsNotNone(setup)

    def test_higher_low_is_long(self) -> None:
        base = _aligned_base()
        highs = [12] * 12
        lows = [8, 8.2, 8.1, 8.4, 8.3, 8.5, 9, 9.1, 9.2, 10, 11, 11, 10.5]
        bars = _bars(base, highs, lows)
        state = SymbolState("XUSDT", last_price=11.0, turnover_24h_usdt=2_000_000.0)
        state.bars_htf["5"] = bars
        trough_ts = base + 9 * STEP
        now_ms = trough_ts + 3 * STEP + 60_000
        snap = {
            "interval": "5",
            "peaks": [],
            "troughs": [{"time_ms": trough_ts, "price": 10.0, "left_strength": 30}],
        }
        with patch("signal_engine.paper.m5_htf.snapshot_pivot_levels", return_value=snap):
            pyl = evaluate_pyl(state, now_ms, None)
        self.assertTrue(pyl["passed"], pyl.get("failed"))
        self.assertEqual(pyl.get("side"), "long")
        self.assertEqual(pyl["metrics"]["pivot_time_ms"], trough_ts)

    def test_setup_ignores_non_tz_local_high(self) -> None:
        """Локальный high без L15–L30 не даёт вход, даже если 15m/30m проходят."""
        state, now_ms, peak_ts = _lower_high_state()
        self.assertIsNone(m5_htf_setup(state, now_ms))

    def test_picks_highest_left_strength_in_window(self) -> None:
        state, now_ms, peak_ts = _lower_high_state()
        weak_ts = peak_ts - 4 * STEP
        snap = {
            "interval": "5",
            "peaks": [
                {"time_ms": weak_ts, "price": 11.5, "left_strength": 15},
                {"time_ms": peak_ts, "price": 12.0, "left_strength": 30},
            ],
            "troughs": [],
        }
        with patch("signal_engine.paper.m5_htf.snapshot_pivot_levels", return_value=snap):
            setup = htf_pivot_setup(state, now_ms, "5")
        self.assertIsNotNone(setup)
        self.assertEqual(setup["pivot_time_ms"], peak_ts)
        self.assertEqual(setup.get("left_strength"), 30)

    def test_pending_after_first_right_bar(self) -> None:
        state, now_ms, peak_ts = _lower_high_state()
        self.assertFalse(htf_second_bar_pending(state, now_ms))
        state.bars_htf["5"] = [b for b in state.bars_htf["5"] if int(b.timestamp) <= peak_ts + STEP]
        pending_now = peak_ts + 2 * STEP + 1_000
        self.assertTrue(htf_second_bar_pending(state, pending_now))

    def test_any_opposite_pivot_closes_without_15m_confirmation(self) -> None:
        base = _aligned_base()
        highs = [20.0] + [10.0] * 15 + [12.0, 11.0, 11.0]
        bars = _bars(base, highs, [9.0] * len(highs))
        peak_ts = base + 16 * STEP
        now_ms = peak_ts + 3 * STEP + 500
        state = SymbolState("XUSDT", last_price=11.0, turnover_24h_usdt=2_000_000.0)
        state.bars_htf["5"] = bars
        pyl = evaluate_pyl(state, now_ms, None)
        self.assertFalse(pyl["passed"])
        hit = opposite_appeared(state, now_ms + 11_000, "long", peak_ts, "5")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["side"], "short")
        self.assertEqual(hit["pivot_time_ms"], peak_ts)
        self.assertIsNone(
            opposite_pivot_exit_signal(state, peak_ts + 2 * STEP + 1_000, "long", base, "5")
        )
        self.assertIsNotNone(
            opposite_pivot_exit_signal(state, peak_ts + 3 * STEP, "long", base, "5")
        )
        self.assertIsNone(opposite_appeared(state, now_ms + 11_000, "short", peak_ts, "5"))
        self.assertIsNone(opposite_appeared(state, now_ms + 11_000, "long", now_ms + 11_000, "5"))


class Vps15OppositeExitTest(unittest.TestCase):
    def test_closes_in_ten_seconds_after_opposite_anchor_trough(self) -> None:
        step = 900_000
        base = T0 - (T0 % (6 * step))
        n = 40
        highs = [100.0] * n
        lows = [98.0] * n
        highs[10] = 105.0
        lows[20] = 94.0
        entry_peak = base + 10 * step
        opp_trough = base + 20 * step
        bars15: list[Bar] = []
        for i in range(n):
            mid = (highs[i] + lows[i]) / 2
            bars15.append(Bar(base + i * step, mid, highs[i], lows[i], mid, 1.0))
        opened_at = entry_peak + step
        confirm_at = second_bar_close_ms(opp_trough, "15")
        state = SymbolState("XUSDT", last_price=99.0, turnover_24h_usdt=2_000_000.0)
        state.bars_htf["15"] = bars15
        with patch("signal_engine.paper.m5_htf.snapshot_pivot_levels") as snap_fn:
            snap_fn.return_value = {
                "peaks": [{"time_ms": entry_peak, "price": 105.0, "left_strength": 17}],
                "troughs": [{"time_ms": opp_trough, "price": 94.0, "left_strength": 21}],
            }
            inside = opposite_anchor_pivot_exit(state, confirm_at + 2_000, "short", opened_at, "15")
            still = opposite_anchor_pivot_exit(state, confirm_at + 90_000, "short", opened_at, "15")
            outside = opposite_anchor_pivot_exit(state, confirm_at + 130_000, "short", opened_at, "15")
        self.assertIsNotNone(inside)
        self.assertEqual(inside["side"], "long")
        self.assertIsNotNone(still)
        self.assertIsNone(outside)


class PivotConfirmClockTest(unittest.TestCase):
    def test_fifteen_min_window_is_ten_seconds(self) -> None:
        pivot = T0 - (T0 % 900_000)
        close_at = second_bar_close_ms(pivot, "15")
        self.assertEqual(close_at, pivot + 3 * 900_000)
        self.assertTrue(just_confirmed(pivot, close_at + 1_000, "15"))
        self.assertFalse(just_confirmed(pivot, close_at + 11_000, "15"))
        self.assertTrue(first_bar_waiting(pivot, close_at - 1_000, "15"))

    def test_five_min_entry_on_third_bar_only(self) -> None:
        pivot = T0
        self.assertEqual(third_bar_open_ms(pivot, "5"), pivot + 3 * STEP)
        self.assertEqual(third_bar_close_ms(pivot, "5"), pivot + 4 * STEP)
        self.assertFalse(entry_on_third_bar(pivot, pivot + 3 * STEP - 1, "5"))
        self.assertTrue(entry_on_third_bar(pivot, pivot + 3 * STEP, "5"))
        self.assertTrue(entry_on_third_bar(pivot, pivot + 4 * STEP - 1, "5"))
        self.assertFalse(entry_on_third_bar(pivot, pivot + 4 * STEP, "5"))
        close_at = second_bar_close_ms(pivot, "5")
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
        self.assertTrue(entry_on_third_bar(peak_ts, third_bar_open_ms(peak_ts, "5") + 500, "5"))

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
