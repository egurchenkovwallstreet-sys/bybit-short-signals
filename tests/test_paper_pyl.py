# -*- coding: utf-8 -*-
"""БАБЛОСОС $$$: M5 LH pivot, стоп от свечи pivot."""

from __future__ import annotations

import unittest

import config
from signal_engine.paper.lh_scan_pivot import signal_from_pivot_diff
from signal_engine.paper.position import bab_pivot_stop_price, price_for_roe
from signal_engine.paper.pyl_detect import PYL_MANDATORY


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

    def test_mandatory_count(self) -> None:
        self.assertEqual(len(PYL_MANDATORY), 4)


if __name__ == "__main__":
    unittest.main()
