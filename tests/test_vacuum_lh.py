"""Пылесос LH: цепочка понижающихся вершин на 1H."""

from __future__ import annotations

import unittest

from signal_engine.state import Bar, SymbolState
from signal_engine.vacuum_lh import (
    last_lower_high_peaks,
    price_below_recent_peaks,
    project_peaks_to_15m,
    scan_symbol,
)

H = 3_600_000
NOW = 1_700_000_000_000


def _peak_bar(ts: int, peak: float) -> Bar:
    return Bar(ts, peak - 0.2, peak, peak - 0.5, peak - 0.3, 100.0)


def _valley_bar(ts: int, base: float) -> Bar:
    return Bar(ts, base + 0.2, base + 0.4, base, base + 0.1, 50.0)


class VacuumLhPeaksTest(unittest.TestCase):
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
        peaks = last_lower_high_peaks(bars, NOW + H, count=5, wing=1)
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

    def test_project_to_15m(self) -> None:
        t = 1_700_000_000_000
        proj = project_peaks_to_15m([{"time": t, "price": 1.23}])
        self.assertEqual(proj[0]["time_15m_ms"], (t // 900_000) * 900_000)

    def test_scan_filters_turnover_and_price(self) -> None:
        peak_prices = [100.0, 90.0, 80.0, 70.0]
        bars: list[Bar] = []
        t = NOW - 50 * H
        for _ in range(12):
            bars.append(_valley_bar(t, 50.0))
            t += H
        for peak in peak_prices:
            bars.extend(
                [
                    _valley_bar(t, peak - 6),
                    _valley_bar(t + H, peak - 5),
                    _peak_bar(t + 2 * H, peak),
                    _valley_bar(t + 3 * H, peak - 4),
                    _valley_bar(t + 4 * H, peak - 5),
                ]
            )
            t += 5 * H
        state = SymbolState(
            "XUSDT",
            bars_htf={"60": bars},
            last_price=65.0,
            turnover_24h_usdt=500_000.0,
        )
        row = scan_symbol(state, NOW + 2 * H)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertLess(row["last_price"], min(p["price"] for p in row["peaks"]))
        state.turnover_24h_usdt = 100_000.0
        self.assertIsNone(scan_symbol(state, NOW + H))


if __name__ == "__main__":
    unittest.main()
