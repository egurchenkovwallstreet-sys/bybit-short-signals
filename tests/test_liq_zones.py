"""Зоны ликвидации: формулы и агрегация."""

from __future__ import annotations

import unittest

from signal_engine.liq_zones import (
    estimate_liquidation_zones,
    isolated_liq_long,
    isolated_liq_short,
)


class LiqZonesTest(unittest.TestCase):
    def test_long_liq_below_entry(self) -> None:
        entry = 100.0
        liq = isolated_liq_long(entry, 10)
        self.assertLess(liq, entry)
        self.assertGreater(liq, entry * 0.85)

    def test_short_liq_above_entry(self) -> None:
        entry = 100.0
        liq = isolated_liq_short(entry, 10)
        self.assertGreater(liq, entry)
        self.assertLess(liq, entry * 1.15)

    def test_hist_clusters_in_band(self) -> None:
        mark = 1.0
        events = [
            {"time": 1_700_000_000_000, "price": 0.92, "size": 1000, "side": "Buy"},
            {"time": 1_700_000_100_000, "price": 0.93, "size": 500, "side": "Buy"},
            {"time": 1_700_000_200_000, "price": 1.08, "size": 800, "side": "Sell"},
        ]
        out = estimate_liquidation_zones(
            mark=mark,
            liquidations=events,
            depth_pct=0.35,
            now_ms=1_700_000_300_000,
        )
        sides = {z["side"] for z in out["zones"]}
        self.assertIn("long", sides)
        self.assertIn("short", sides)
        for z in out["zones"]:
            self.assertGreaterEqual(z["price"], out["lo"])
            self.assertLessEqual(z["price"], out["hi"])

    def test_oi_model_adds_levels(self) -> None:
        mark = 100.0
        oi = [
            {"timestamp": 1_000_000, "open_interest": 1000},
            {"timestamp": 1_300_000, "open_interest": 1100},
        ]
        candles = [{"timestamp": 1_200_000, "close": 100.0}]
        out = estimate_liquidation_zones(mark=mark, oi_rows=oi, candles=candles, depth_pct=0.2, now_ms=2_000_000)
        self.assertTrue(out["zones"])


if __name__ == "__main__":
    unittest.main()
