"""Пылесос LH: цепочка понижающихся вершин на 1H."""

from __future__ import annotations

import unittest

from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import (
    filter_pivots_min_bar_gap,
    pivot_highs_asymmetric_indexed,
    pivot_highs_floating_left_indexed,
)
from signal_engine.vacuum_lh import (
    all_anchor_peaks,
    apply_peak_confluence,
    apply_senior_mtf_confluence,
    build_vacuum_lh_boards,
    senior_intervals_for_chart,
    classify_lh_hl_structure,
    hour_range_pct,
    structure_trend_on_interval,
    VACUUM_LH_STRUCTURE_INTERVAL,
    confluence_index,
    last_higher_low_troughs,
    last_lower_high_peaks,
    pivots_from_bars,
    price_below_recent_peaks,
    project_peaks_to_chart,
    project_troughs_to_chart,
    scan_symbol,
    union_pivot_points,
)

H = 3_600_000
NOW = 1_700_000_000_000
# Под pivot 15–30 и min gap 15 на 1H
_PIVOT_PAD_BARS = 20


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
        for _ in range(_PIVOT_PAD_BARS):
            bars.append(_valley_bar(t, 50.0))
            t += H
        for peak in peak_prices:
            floor = min(40.0, peak - 20.0)
            for _ in range(_PIVOT_PAD_BARS):
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
        chain = last_lower_high_peaks(bars, "60", scan_now, count=5)
        self.assertGreaterEqual(len(anchors), len(chain))

    def test_pivot_min_gap_seven_bars(self) -> None:
        pivots = [
            {"bar_index": 0, "price": 10.0, "time": 0, "left_strength": 7},
            {"bar_index": 3, "price": 11.0, "time": 3, "left_strength": 7},
            {"bar_index": 10, "price": 9.0, "time": 10, "left_strength": 12},
        ]
        out = filter_pivots_min_bar_gap(pivots, 10, kind="peak")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["bar_index"], 3)
        self.assertEqual(out[0]["price"], 11.0)

    def test_pivot_gap_prefers_price_extreme(self) -> None:
        pivots = [
            {"bar_index": 0, "price": 12.0, "left_strength": 16},
            {"bar_index": 20, "price": 11.0, "left_strength": 28},
        ]
        out = filter_pivots_min_bar_gap(pivots, 10, kind="peak")
        self.assertEqual(len(out), 2)

    def test_pivot_gap_trough_prefers_lower_low(self) -> None:
        pivots = [
            {"bar_index": 0, "price": 5.0, "left_strength": 28},
            {"bar_index": 15, "price": 4.2, "left_strength": 15},
        ]
        out = filter_pivots_min_bar_gap(pivots, 10, kind="trough")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[-1]["price"], 4.2)

    def test_pivot_gap_three_in_thirty_window(self) -> None:
        pivots = [
            {"bar_index": 0, "price": 10.0, "left_strength": 12},
            {"bar_index": 12, "price": 11.0, "left_strength": 12},
            {"bar_index": 24, "price": 9.5, "left_strength": 12},
        ]
        out = filter_pivots_min_bar_gap(pivots, 10, kind="peak")
        self.assertEqual(len(out), 3)

    def test_plateau_peak_second_bar_with_two_lower_right(self) -> None:
        """Две свечи с одним high — pivot на второй, если справа 2 ниже."""
        t0 = NOW
        bars: list[Bar] = []
        for i in range(12):
            h = 0.5 + i * 0.01
            bars.append(Bar(t0 + i * H, h - 0.02, h, h - 0.05, h - 0.03, 1.0))
        i_first = len(bars)
        bars.append(Bar(t0 + i_first * H, 0.98, 1.0, 0.95, 0.97, 1.0))
        i_second = len(bars)
        bars.append(Bar(t0 + i_second * H, 0.99, 1.0, 0.96, 0.98, 1.0))
        bars.append(Bar(t0 + (i_second + 1) * H, 0.92, 0.94, 0.90, 0.91, 1.0))
        bars.append(Bar(t0 + (i_second + 2) * H, 0.88, 0.90, 0.86, 0.87, 1.0))
        pivots = pivot_highs_floating_left_indexed(bars, left_min=10, left_max=30, right=2)
        idxs = {int(p["bar_index"]) for p in pivots}
        self.assertIn(i_second, idxs)
        self.assertNotIn(i_first, idxs)
        hit = next(p for p in pivots if int(p["bar_index"]) == i_second)
        self.assertAlmostEqual(float(hit["price"]), 1.0)

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
        t = NOW - 200 * H
        for _ in range(_PIVOT_PAD_BARS):
            bars.append(_valley_bar(t, 70.0))
            t += H
        for peak in peak_prices:
            for _ in range(_PIVOT_PAD_BARS):
                bars.append(_valley_bar(t, peak - 25))
                t += H
            bars.append(_peak_bar(t, peak))
            t += H
            for _ in range(3):
                bars.append(_valley_bar(t, peak - 20))
                t += H
        peaks = last_lower_high_peaks(bars, "60", t + H, count=5)
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
        t = NOW - 200 * H
        for _ in range(_PIVOT_PAD_BARS):
            bars.append(_peak_bar(t, 120.0))
            t += H
        for trough in trough_prices:
            for _ in range(_PIVOT_PAD_BARS):
                bars.append(_peak_bar(t, trough + 30))
                t += H
            bars.append(_trough_bar(t, trough))
            t += H
            for _ in range(3):
                bars.append(_peak_bar(t, trough + 25))
                t += H
        troughs = last_higher_low_troughs(bars, "60", t + H, count=4)
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

    def test_senior_mtf_ladder_intervals(self) -> None:
        self.assertEqual(senior_intervals_for_chart("5"), ("15", "30", "60"))
        self.assertEqual(senior_intervals_for_chart("60"), ("240",))
        self.assertEqual(senior_intervals_for_chart("240"), ())

    def test_senior_mtf_match_by_price_and_bucket(self) -> None:
        t5 = 1_700_000_000_000
        step15 = 900_000
        t15 = (t5 // step15) * step15
        point = {"time_ms": t5, "price": 1.234}
        indexes = {
            "15": {(t15, 1.234)},
            "30": set(),
            "60": set(),
        }
        out = apply_senior_mtf_confluence([point], indexes)
        self.assertEqual(out[0]["tf_match_count"], 1)
        self.assertEqual(out[0]["tf_matches"], ["15"])

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

    def test_scan_lists_by_turnover_even_if_price_above_peaks(self) -> None:
        peak_prices = [100.0, 90.0, 80.0, 70.0]
        bars: list[Bar] = []
        t = NOW - 50 * H
        for _ in range(_PIVOT_PAD_BARS):
            bars.append(_valley_bar(t, 50.0))
            t += H
        for peak in peak_prices:
            floor = min(40.0, peak - 20.0)
            for _ in range(_PIVOT_PAD_BARS):
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
        minutes = [
            Bar(scan_now - (12 - i) * 60_000, 200.0, 207.0, 199.0, 200.0, 1.0) for i in range(12)
        ]
        state = SymbolState(
            "XUSDT",
            bars_1m=minutes,
            bars_htf={"60": bars},
            last_price=200.0,
            turnover_24h_usdt=1_100_000.0,
        )
        row = scan_symbol(state, scan_now)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertGreater(row["last_price"], max(p["price"] for p in row["all_peaks"] or row["peaks"] or [{"price": 0}]))
        state.turnover_24h_usdt = 500_000.0
        self.assertIsNone(scan_symbol(state, scan_now))


class VacuumHourRangeTest(unittest.TestCase):
    def _minutes(self, now_ms: int, high: float, low: float, n: int = 12) -> list[Bar]:
        return [
            Bar(now_ms - (n - i) * 60_000, 100.0, high, low, 100.0, 1.0) for i in range(n)
        ]

    def test_two_percent_passes(self) -> None:
        now = NOW
        state = SymbolState("X", bars_1m=self._minutes(now, 102.0, 100.0), last_price=100.0)
        self.assertAlmostEqual(hour_range_pct(state, now, 100.0), 2.0)
        state.turnover_24h_usdt = 1_100_000.0
        state.bars_htf["60"] = [_valley_bar(now - i * H, 90.0) for i in range(30, 0, -1)]
        self.assertIsNotNone(scan_symbol(state, now))

    def test_below_two_percent_rejected(self) -> None:
        now = NOW
        state = SymbolState(
            "X",
            bars_1m=self._minutes(now, 101.9, 100.0),
            last_price=100.0,
            turnover_24h_usdt=1_100_000.0,
            bars_htf={"60": [_valley_bar(now - i * H, 90.0) for i in range(30, 0, -1)]},
        )
        self.assertAlmostEqual(hour_range_pct(state, now, 100.0), 1.9)
        self.assertIsNone(scan_symbol(state, now))

    def test_no_hour_bars_rejected(self) -> None:
        now = NOW
        state = SymbolState(
            "X",
            last_price=100.0,
            turnover_24h_usdt=1_100_000.0,
            bars_htf={"60": [_valley_bar(now - i * H, 90.0) for i in range(30, 0, -1)]},
        )
        self.assertIsNone(hour_range_pct(state, now, 100.0))
        self.assertIsNone(scan_symbol(state, now))


class VacuumChartPivotTest(unittest.TestCase):
    def test_union_keeps_old_and_new(self) -> None:
        old = [{"time_ms": 1, "price": 10.0, "left_strength": 15, "index": 1}]
        fresh = [{"time_ms": 2, "price": 12.0, "left_strength": 22, "tf_match_count": 1}]
        out = union_pivot_points(old, fresh)
        self.assertEqual([p["price"] for p in out], [10.0, 12.0])

    def test_board_carries_5m_chart_pivots(self) -> None:
        board = build_vacuum_lh_boards({}, NOW)
        self.assertIn("5", board["data"]["chart_pivots"])

    def test_anchor_outside_lh_chain_stays(self) -> None:
        bars: list[Bar] = []
        t = NOW - 400 * H
        peaks = [100.0, 70.0, 90.0, 60.0, 80.0]
        for peak in peaks:
            for _ in range(40):
                bars.append(_valley_bar(t, peak - 30.0))
                t += H
            bars.append(_peak_bar(t, peak))
            t += H
        for _ in range(8):
            bars.append(_valley_bar(t, 20.0))
            t += H
        scan_now = t
        packed = pivots_from_bars(bars, "60", scan_now)
        anchor_px = {round(float(p["price"]), 4) for p in packed["anchor_peaks"]}
        chain_px = {round(float(p["price"]), 4) for p in packed["peaks"]}
        ghost_px = {round(float(p["price"]), 4) for p in packed["ghost_peaks"]}
        self.assertTrue(chain_px)
        self.assertTrue(chain_px <= anchor_px)
        self.assertTrue(len(anchor_px) >= len(chain_px))

    def test_broken_peak_is_ghost_not_anchor(self) -> None:
        """После подтверждения pivot-high пробит — только ghost, не anchor."""
        bars: list[Bar] = []
        t = NOW - 80 * H
        for _ in range(_PIVOT_PAD_BARS):
            bars.append(_valley_bar(t, 50.0))
            t += H
        peak_ts = t
        bars.append(_peak_bar(peak_ts, 100.0))
        t += H
        for _ in range(3):
            bars.append(_valley_bar(t, 70.0))
            t += H
        bars.append(_peak_bar(t, 101.0))
        t += H
        for _ in range(6):
            bars.append(_valley_bar(t, 60.0))
            t += H
        scan_now = t + 2 * H
        packed = pivots_from_bars(bars, "60", scan_now)
        anchor_px = {round(float(p["price"]), 4) for p in packed["anchor_peaks"]}
        active_px = {round(float(p["price"]), 4) for p in packed["all_peaks"]}
        self.assertTrue(anchor_px)
        self.assertTrue(active_px <= anchor_px or anchor_px - active_px)
        self.assertNotIn(100.0, active_px)


if __name__ == "__main__":
    unittest.main()
