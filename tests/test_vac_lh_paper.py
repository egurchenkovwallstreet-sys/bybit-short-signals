"""Paper Пылесос 15/5: вход по одному прошлому pivot."""

from __future__ import annotations

import unittest

from signal_engine.paper.vac_lh_detect import detect_entry_signal, side_for_new_peak, side_for_new_trough


class VacLhPaperDetectTest(unittest.TestCase):
    def test_short_one_prev_lower(self) -> None:
        peaks = [
            {"time_ms": 1, "price": 10.0},
            {"time_ms": 2, "price": 8.0},
        ]
        self.assertEqual(side_for_new_peak(peaks, (2, 8.0)), "short")
        self.assertIsNone(side_for_new_peak(peaks[:1], (1, 10.0)))

    def test_long_one_prev_higher(self) -> None:
        troughs = [
            {"time_ms": 1, "price": 5.0},
            {"time_ms": 2, "price": 6.0},
        ]
        self.assertEqual(side_for_new_trough(troughs, (2, 6.0)), "long")

    def test_detect_from_snap_diff(self) -> None:
        prev = {"peaks": [{"time_ms": 1, "price": 10.0}], "troughs": []}
        cur = {
            "peaks": [{"time_ms": 1, "price": 10.0}, {"time_ms": 2, "price": 9.0}],
            "troughs": [],
        }
        sig = detect_entry_signal(prev, cur)
        self.assertIsNotNone(sig)
        assert sig is not None
        self.assertEqual(sig["side"], "short")


if __name__ == "__main__":
    unittest.main()
