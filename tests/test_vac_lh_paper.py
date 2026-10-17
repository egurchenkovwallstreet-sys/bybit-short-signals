"""Paper Пылесос: max → шорт, min → лонг; вход — 1-я незакрытая свеча после 2 подтверждений."""

from __future__ import annotations

import unittest

from signal_engine.paper.vac_lh_detect import (
    detect_entry_signal,
    entry_open_until_ms,
    entry_window_start_ms,
    latest_qualifying_signal,
    pivot_in_entry_window,
)


def _in_window_now(pivot_time_ms: int) -> int:
    return entry_window_start_ms(pivot_time_ms, "5") + 1


class VacLhPaperDetectTest(unittest.TestCase):
    def test_new_peak_is_short_even_if_higher_than_prev(self) -> None:
        prev = {"peaks": [{"time_ms": 1, "price": 8.0}], "troughs": []}
        cur = {
            "peaks": [
                {"time_ms": 1, "price": 8.0},
                {"time_ms": 1_000_000, "price": 10.0},
            ],
            "troughs": [],
        }
        sig = detect_entry_signal(prev, cur, "5", _in_window_now(1_000_000))
        self.assertIsNotNone(sig)
        assert sig is not None
        self.assertEqual(sig["side"], "short")

    def test_new_trough_is_long_even_if_lower_than_prev(self) -> None:
        prev = {"peaks": [], "troughs": [{"time_ms": 1, "price": 6.0}]}
        cur = {
            "peaks": [],
            "troughs": [
                {"time_ms": 1, "price": 6.0},
                {"time_ms": 1_000_000, "price": 5.0},
            ],
        }
        sig = detect_entry_signal(prev, cur, "5", _in_window_now(1_000_000))
        assert sig is not None
        self.assertEqual(sig["side"], "long")

    def test_latest_pivot_by_time_in_window(self) -> None:
        cur = {
            "peaks": [{"time_ms": 1_000_000, "price": 10.0}],
            "troughs": [{"time_ms": 1_300_000, "price": 5.0}],
        }
        sig = latest_qualifying_signal(cur, "5", _in_window_now(1_300_000))
        assert sig is not None
        self.assertEqual(sig["side"], "long")

    def test_before_entry_candle_no_signal(self) -> None:
        pivot = 1_000_000
        cur = {"peaks": [{"time_ms": pivot, "price": 10.0}], "troughs": []}
        now_ms = entry_window_start_ms(pivot, "5") - 1
        self.assertFalse(pivot_in_entry_window(pivot, "5", now_ms))
        self.assertIsNone(latest_qualifying_signal(cur, "5", now_ms))

    def test_stale_pivot_after_entry_candle_no_signal(self) -> None:
        pivot = 1_000_000
        cur = {"peaks": [{"time_ms": pivot, "price": 10.0}], "troughs": []}
        now_ms = entry_open_until_ms(pivot, "5") + 1
        self.assertFalse(pivot_in_entry_window(pivot, "5", now_ms))
        self.assertIsNone(latest_qualifying_signal(cur, "5", now_ms))

    def test_catch_up_after_restart_in_window(self) -> None:
        pivot = 1_000_000
        cur = {
            "peaks": [
                {"time_ms": 100, "price": 9.0},
                {"time_ms": pivot, "price": 10.0},
            ],
            "troughs": [],
        }
        sig = detect_entry_signal(None, cur, "5", _in_window_now(pivot))
        assert sig is not None
        self.assertEqual(sig["pivot_time_ms"], pivot)
        self.assertEqual(sig["side"], "short")


if __name__ == "__main__":
    unittest.main()
