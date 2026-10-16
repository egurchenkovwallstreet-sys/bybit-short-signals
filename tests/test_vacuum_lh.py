"""Пылесос LH: цепочка понижающихся вершин на 1H."""

from __future__ import annotations

import unittest

from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import (
    pivot_highs_asymmetric_indexed,
    pivot_highs_floating_left_indexed,
)
from signal_engine.vacuum_lh import (
    all_anchor_peaks,
    apply_peak_confluence,
    classify_lh_hl_structure,
    structure_trend_on_interval,
    VACUUM_LH_STRUCTURE_INTERVAL,
    confluence_index,
    last_higher_low_troughs,
    last_lower_high_peaks,
    price_below_recent_peaks,
    project_peaks_to_chart,
    project_troughs_to_chart,
    scan_symbol,
)

H = 3_600_000
NOW = 1_700_000_000_000


def _peak_bar(ts: int, peak: float) -> Bar:
    return Bar(ts, peak - 0.2, peak, peak - 0.5, peak - 0.3, 100.0)


def _valley_bar(ts: int, base: float) -> Bar:
    return Bar(ts, base + 0.2, base + 0.4, base, base + 0.1, 50.0)


def _trough_bar(ts: int, trough: float) -> Bar:
    return Bar(ts, trough + 0.5, trough + 0.8, trough, trough + 0.3, 100.0)


class VacuumLhPeaksTest(unittest.TestCase):
    def test_all_anchors_within_chain_count(self) -> None:
        peak_prices = [100.0, 90.0, 80.0, 70.0]
        bars: list[Bar] = []
        t = NOW - 50 * H
        for _ in range(20):
            bars.append(_valley_bar(t, 50.0))
            t += H
        for peak in peak_prices:
            floor = min(40.0, peak - 20.0)
            for _ in range(8):
                bars.append(_valley_bar(t, floor))
                t += H
            bars.append(_peak_bar(t, peak))
            t += H
            for _ in range(3):
                bars.append(_valley_bar(t, floor))
                t += H
        scan_now = t + 5 * H
        for _ in range(6):
            bars.append(_valley_bar(t, 35.0))
            t += H
        anchors = all_anchor_peaks(bars, "60", scan_now)
        chain = last_lower_high_peaks(
            bars, "60", scan_now, count=5, pivot_left=1, pivot_right=1
        )
        self.assertGreaterEqual(len(anchors), len(chain))

    def test_floating_left_strength_up_to_twenty(self) -> None:
        lows = [10.0] * 7 + [20.0, 9.0, 8.0]
        bars = [
            Bar(NOW + i * H, lows[i], lows[i] + 0.1, lows[i] - 0.1, lows[i], 1.0)
            for i in range(len(lows))
        ]
        bars[7] = Bar(NOW + 7 * H, 18.0, 20.0, 17.0, 19.0, 1.0)
        pivots = pivot_highs_floating_left_indexed(bars, left_min=7, left_max=20, right=2)
        self.assertEqual(len(pivots), 1)
        self.assertGreaterEqual(pivots[0]["left_strength"], 7)

    def test_asymmetric_pivot_seven_left_two_right(self) -> None:
        lows = [10.0] * 7 + [20.0, 9.0, 8.0]
        bars = [
            Bar(NOW + i * H, lows[i], lows[i] + 0.1, lows[i] - 0.1, lows[i], 1.0)
            for i in range(len(lows))
        ]
        bars[7] = Bar(NOW + 7 * H, 18.0, 20.0, 17.0, 19.0, 1.0)
        pivots = pivot_highs_asymmetric_indexed(bars, left=7, right=2)
        self.assertEqual(len(pivots), 1)
        self.assertEqual(pivots[0]["price"], 20.0)
        self.assertEqual(pivots[0]["bar_index"], 7)

    def test_five_lower_highs_chain(self) -> None:
        # Убывающие вершины: 100 → 95 → 90 → 88 → 85 (между — провалы для pivot wing=1)
        peak_prices = [100.0, 95.0, 90.0, 88.0, 85.0]
        bars: list[Bar] = []
        t = NOW - 30 * H
        for peak in peak_prices:
            bars.append(_valley_bar(t, peak - 5))
            t += H
            bars.append(_peak_bar(t, peak))
            t += H
            bars.append(_valley_bar(t, peak - 4))
            t += H
        peaks = last_lower_high_peaks(
            bars, "60", NOW + H, count=5, pivot_left=1, pivot_right=1
        )
        self.assertGreaterEqual(len(peaks), 2)
        prices = [p["price"] for p in peaks]
        for i in range(1, len(prices)):
            self.assertLess(prices[i], prices[i - 1])

    def test_price_must_be_below_last_three(self) -> None:
        peaks = [{"price": 12.0}, {"price": 10.0}, {"price": 9.0}, {"price": 8.0}]
        self.assertTrue(price_below_recent_peaks(7.5, peaks, last_n=3))
        self.assertFalse(price_below_recent_peaks(8.5, peaks, last_n=3))
        self.assertFalse(price_below_recent_peaks(11.0, peaks, last_n=3))
        self.assertTrue(price_below_recent_peaks(7.5, peaks, last_n=1))

    def test_project_to_chart(self) -> None:
        t = 1_700_000_000_000
        proj = project_peaks_to_chart([{"time": t, "price": 1.23}], "60")
        self.assertEqual(proj[0]["time_chart_ms"], (t // 3_600_000) * 3_600_000)

    def test_higher_lows_chain(self) -> None:
        trough_prices = [80.0, 85.0, 90.0, 92.0]
        bars: list[Bar] = []
        t = NOW - 30 * H
        for trough in trough_prices:
            bars.append(_peak_bar(t, trough + 15))
            t += H
            bars.append(_trough_bar(t, trough))
            t += H
            bars.append(_peak_bar(t, trough + 12))
            t += H
        troughs = last_higher_low_troughs(
            bars, "60", NOW + H, count=4, pivot_left=1, pivot_right=1
        )
        self.assertGreaterEqual(len(troughs), 2)
        prices = [p["price"] for p in troughs]
        for i in range(1, len(prices)):
            self.assertGreater(prices[i], prices[i - 1])

    def test_structure_uses_4h_interval_constant(self) -> None:
        self.assertEqual(VACUUM_LH_STRUCTURE_INTERVAL, "240")

    def test_structure_trend_columns(self) -> None:
        peaks = [{"price": 10}, {"price": 9}, {"price": 8}]
        troughs = [{"price": 5}, {"price": 4}, {"price": 3}]
        self.assertEqual(classify_lh_hl_structure(peaks, troughs), "down")
        peaks_up = [{"price": 8}, {"price": 9}, {"price": 10}]
        troughs_up = [{"price": 3}, {"price": 4}, {"price": 5}]
        self.assertEqual(classify_lh_hl_structure(peaks_up, troughs_up), "up")
        self.assertEqual(classify_lh_hl_structure(peaks, troughs_up), "mixed")

    def test_trough_confluence_same_time_and_price(self) -> None:
        t = 1_700_000_000_000
        tr60 = project_troughs_to_chart([{"time": t, "price": 3.0}], "60")
        tr30 = project_troughs_to_chart([{"time": t, "price": 3.0}], "30")
        idx = confluence_index({"60": tr60, "30": tr30})
        out = apply_peak_confluence(tr60, idx)
        self.assertTrue(out[0]["confluence"])
        self.assertEqual(out[0]["tf_match_count"], 2)

    def test_confluence_same_time_and_price(self) -> None:
        t = 1_700_000_000_000
        p60 = project_peaks_to_chart([{"time": t, "price": 5.0}], "60")
        p30 = project_peaks_to_chart([{"time": t, "price": 5.0}], "30")
        idx = confluence_index({"60": p60, "30": p30, "5": []})
        out = apply_peak_confluence(p60, idx)
        self.assertTrue(out[0]["confluence"])
        self.assertEqual(out[0]["tf_match_count"], 2)
        self.assertIn("60", out[0]["tf_matches"])
        self.assertIn("30", out[0]["tf_matches"])

    def test_scan_filters_turnover_and_price(self) -> None:
        peak_prices = [100.0, 90.0, 80.0, 70.0]
        bars: list[Bar] = []
        t = NOW - 50 * H
        for _ in range(20):
            bars.append(_valley_bar(t, 50.0))
            t += H
        for peak in peak_prices:
            floor = min(40.0, peak - 20.0)
            for _ in range(8):
                bars.append(_valley_bar(t, floor))
                t += H
            bars.append(_peak_bar(t, peak))
            t += H
            for _ in range(3):
                bars.append(_valley_bar(t, floor))
                t += H
        scan_now = t + 5 * H
        for _ in range(6):
            bars.append(_valley_bar(t, 35.0))
            t += H
        state = SymbolState(
            "XUSDT",
            bars_htf={"60": bars},
            last_price=65.0,
            turnover_24h_usdt=500_000.0,
        )
        row = scan_symbol(state, scan_now)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertLess(row["last_price"], min(p["price"] for p in row["peaks"]))
        state.turnover_24h_usdt = 100_000.0
        self.assertIsNone(scan_symbol(state, scan_now))


if __name__ == "__main__":
    unittest.main()
