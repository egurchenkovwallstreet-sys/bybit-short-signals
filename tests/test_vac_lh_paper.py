"""Paper Пылесос: max → шорт, min → лонг."""

from __future__ import annotations

import unittest

from signal_engine.paper.vac_lh_detect import detect_entry_signal, latest_qualifying_signal


class VacLhPaperDetectTest(unittest.TestCase):
    def test_new_peak_is_short_even_if_higher_than_prev(self) -> None:
        prev = {"peaks": [{"time_ms": 1, "price": 8.0}], "troughs": []}
        cur = {
            "peaks": [
                {"time_ms": 1, "price": 8.0},
                {"time_ms": 2, "price": 10.0},
            ],
            "troughs": [],
        }
        sig = detect_entry_signal(prev, cur)
        self.assertIsNotNone(sig)
        assert sig is not None
        self.assertEqual(sig["side"], "short")

    def test_new_trough_is_long_even_if_lower_than_prev(self) -> None:
        prev = {"peaks": [], "troughs": [{"time_ms": 1, "price": 6.0}]}
        cur = {
            "peaks": [],
            "troughs": [
                {"time_ms": 1, "price": 6.0},
                {"time_ms": 2, "price": 5.0},
            ],
        }
        sig = detect_entry_signal(prev, cur)
        assert sig is not None
        self.assertEqual(sig["side"], "long")

    def test_latest_pivot_by_time(self) -> None:
        cur = {
            "peaks": [{"time_ms": 1, "price": 10.0}],
            "troughs": [{"time_ms": 2, "price": 5.0}],
        }
        sig = latest_qualifying_signal(cur)
        assert sig is not None
        self.assertEqual(sig["side"], "long")


if __name__ == "__main__":
    unittest.main()
