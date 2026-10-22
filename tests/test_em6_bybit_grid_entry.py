"""EMA6 Bybit: сетка уровней и FSM входа."""

from __future__ import annotations

import unittest

from signal_engine.live.em6_bybit.grid_entry import (
    CandidateWatch,
    band_lo,
    pick_top_candidates,
)


class TestGridBands(unittest.TestCase):
    def test_band_lo_fractional(self) -> None:
        self.assertEqual(band_lo(6.7), 6.5)
        self.assertEqual(band_lo(4.0), 4.0)

    def test_pick_top(self) -> None:
        rows = [
            ("A", "long", 5.0, 1.0),
            ("B", "short", 8.0, 1.0),
            ("C", "long", 4.2, 1.0),
        ]
        top = pick_top_candidates(rows, limit=2)
        self.assertEqual([t[0] for t in top], ["B", "A"])


class TestCandidateFsm(unittest.TestCase):
    def test_entry_after_cross_and_1m(self) -> None:
        w = CandidateWatch(symbol="X", side="long", since_ms=0)
        ema = 100.0
        t = 0
        w.update_peak(t, 7.0, 93.0, ema)
        w.last_band_lo = band_lo(7.0)
        w.away_max_band_lo = w.last_band_lo
        w.stall_band_lo = w.last_band_lo
        w.phase = "stalled"
        w.tick(t + 1000, 7.3, 92.7, ema, None)
        w.tick(t + 2000, 7.45, 92.55, ema, None)
        w.tick(t + 3000, 7.4, 92.6, ema, None)
        self.assertFalse(w.tick(t + 4000, 7.2, 92.8, ema, None))
        close = (t + 120_000, 92.75)
        fired = w.tick(t + 130_000, 7.15, 92.85, ema, close)
        self.assertTrue(fired or w.armed_entry_band_lo is not None)

    def test_band_step_down_arms_each_level(self) -> None:
        w = CandidateWatch(symbol="Y", side="short", since_ms=0)
        ema = 100.0
        w.peak_stretch = 10.0
        w.last_stretch = 10.0
        w.last_band_lo = band_lo(10.0)
        w.away_max_band_lo = w.last_band_lo
        w.phase = "stalled"
        w.tick(1000, 9.5, 109.5, ema, None)
        self.assertIsNotNone(w.armed_entry_band_lo)
        w.tick(2000, 9.0, 109.0, ema, None)
        self.assertLessEqual(w.armed_entry_band_lo, band_lo(9.0))


if __name__ == "__main__":
    unittest.main()
