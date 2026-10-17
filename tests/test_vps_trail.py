"""Трейл Пылесос: −10% и пик − 10 п.п."""

from __future__ import annotations

import unittest

from signal_engine.paper.position import vps_trail_stop_long, vps_trail_stop_short


class VpsTrailTest(unittest.TestCase):
    def test_short_trail_at_entry_matches_floor(self) -> None:
        entry = 100.0
        stop = vps_trail_stop_short(entry, 100.0, leverage=10, margin=50.0, entry_fee=0.0)
        self.assertGreater(stop, entry)

    def test_short_trail_follows_peak(self) -> None:
        entry = 100.0
        stop_flat = vps_trail_stop_short(entry, 95.0, leverage=10, margin=50.0)
        stop_deeper = vps_trail_stop_short(entry, 90.0, leverage=10, margin=50.0)
        self.assertLess(stop_deeper, stop_flat)

    def test_long_trail_follows_peak(self) -> None:
        entry = 100.0
        stop_small = vps_trail_stop_long(entry, 105.0, leverage=10, margin=50.0)
        stop_big = vps_trail_stop_long(entry, 110.0, leverage=10, margin=50.0)
        self.assertGreater(stop_big, stop_small)


if __name__ == "__main__":
    unittest.main()
