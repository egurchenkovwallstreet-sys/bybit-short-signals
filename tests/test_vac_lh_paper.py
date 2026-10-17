"""Paper Пылесос (vps): вход по двум прошлым pivot."""

from __future__ import annotations

import unittest

from signal_engine.paper.vac_lh_detect import detect_entry_signal, side_for_new_peak, side_for_new_trough


class VacLhPaperDetectTest(unittest.TestCase):
    def test_short_needs_two_previous_lower(self) -> None:
        peaks = [
            {"time_ms": 1, "price": 12.0},
            {"time_ms": 2, "price": 10.0},
            {"time_ms": 3, "price": 8.0},
        ]
        self.assertEqual(side_for_new_peak(peaks, (3, 8.0)), "short")
        self.assertIsNone(side_for_new_peak(peaks[:2], (2, 10.0)))

    def test_long_needs_two_previous_higher(self) -> None:
        troughs = [
            {"time_ms": 1, "price": 4.0},
            {"time_ms": 2, "price": 5.0},
            {"time_ms": 3, "price": 6.0},
        ]
        self.assertEqual(side_for_new_trough(troughs, (3, 6.0)), "long")

    def test_detect_from_snap_diff(self) -> None:
        prev = {
            "peaks": [{"time_ms": 1, "price": 12.0}, {"time_ms": 2, "price": 10.0}],
            "troughs": [],
        }
        cur = {
            "peaks": [
                {"time_ms": 1, "price": 12.0},
                {"time_ms": 2, "price": 10.0},
                {"time_ms": 3, "price": 8.0},
            ],
            "troughs": [],
        }
        sig = detect_entry_signal(prev, cur)
        self.assertIsNotNone(sig)
        assert sig is not None
        self.assertEqual(sig["side"], "short")
        self.assertIn("short:", sig["signal_key"])


if __name__ == "__main__":
    unittest.main()
