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

    def test_pending_cleared_split(self) -> None:
        mark = 1.0
        now = 1_700_000_500_000
        events = [
            {"time": now - 3600_000, "price": 0.92, "size": 1000, "side": "Buy"},
        ]
        candles = [
            {"timestamp": now - 7200_000, "high": 1.05, "low": 0.95, "close": 1.0},
            {"timestamp": now - 3600_000, "high": 1.02, "low": 0.88, "close": 0.95},
        ]
        out = estimate_liquidation_zones(
            mark=mark,
            liquidations=events,
            candles=candles,
            depth_pct=0.35,
            now_ms=now,
        )
        self.assertTrue(out["zones"])
        for z in out["zones"]:
            self.assertIn("notional_pending_usd", z)
            self.assertIn("notional_cleared_usd", z)
            self.assertAlmostEqual(
                z["notional_usd"],
                z["notional_pending_usd"] + z["notional_cleared_usd"],
                places=1,
            )
        hist_long = [z for z in out["zones"] if z["side"] == "long" and z["source"] == "hist"]
        self.assertTrue(hist_long)
        self.assertGreater(hist_long[0]["notional_cleared_usd"], 0)

    def test_long_below_mark_stays_pending_without_drop(self) -> None:
        mark = 0.04
        now = 1_700_000_500_000
        candles = [
            {"timestamp": now - 3600_000, "high": 0.041, "low": 0.038, "close": 0.04},
        ]
        out = estimate_liquidation_zones(mark=mark, candles=candles, depth_pct=0.35, now_ms=now)
        longs = [z for z in out["zones"] if z["side"] == "long" and z["price"] < mark * 0.99]
        self.assertTrue(longs)
        for z in longs:
            if z["source"] == "model":
                self.assertGreater(z["notional_pending_usd"], 0)
                self.assertEqual(z["notional_cleared_usd"], 0)


if __name__ == "__main__":
    unittest.main()
