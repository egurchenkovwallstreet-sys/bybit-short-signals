"""15m live pin: новый уровень и колонка."""

from __future__ import annotations

import unittest

from signal_engine.vacuum_lh_live import _column_for_new_peak, _column_for_new_trough, _detect_live_event


class VacuumLhLiveTest(unittest.TestCase):
    def test_new_peak_below_prev_goes_down(self) -> None:
        peaks = [
            {"time_ms": 1, "price": 10.0},
            {"time_ms": 2, "price": 8.0},
        ]
        col = _column_for_new_peak(peaks, (2, 8.0))
        self.assertEqual(col, "down")

    def test_new_trough_above_prev_goes_up(self) -> None:
        troughs = [
            {"time_ms": 1, "price": 5.0},
            {"time_ms": 2, "price": 6.0},
        ]
        col = _column_for_new_trough(troughs, (2, 6.0))
        self.assertEqual(col, "up")

    def test_detect_any_new_level(self) -> None:
        prev = {"peaks": [{"time_ms": 1, "price": 10.0}], "troughs": []}
        cur = {
            "peaks": [{"time_ms": 1, "price": 10.0}, {"time_ms": 2, "price": 9.0}],
            "troughs": [],
        }
        has_new, col = _detect_live_event(prev, cur)
        self.assertTrue(has_new)
        self.assertEqual(col, "down")


if __name__ == "__main__":
    unittest.main()
