"""EMA6 Bybit: адаптивный порог и pre-entry watch."""

from __future__ import annotations

import unittest

import config
from signal_engine.live.em6_bybit.adaptive_entry import (
    AdaptiveStretchRegime,
    PreEntryWatch,
    compute_adaptive_threshold,
    stretch_bucket_lower,
)


class TestAdaptiveBuckets(unittest.TestCase):
    def test_bucket_lower(self) -> None:
        self.assertEqual(stretch_bucket_lower(3.9), None)
        self.assertEqual(stretch_bucket_lower(4.0), 4.0)
        self.assertEqual(stretch_bucket_lower(4.49), 4.0)
        self.assertEqual(stretch_bucket_lower(9.2), 9.0)

    def test_threshold_highest_confirmed(self) -> None:
        stretches = [9.1, 9.2, 9.3, 5.0, 5.1, 5.2, 4.0]
        thr, counts = compute_adaptive_threshold(stretches)
        self.assertEqual(counts.get(9.0), 3)
        self.assertEqual(thr, 9.0)

    def test_raise_if_more_than_five(self) -> None:
        stretches = [9.0 + i * 0.05 for i in range(6)]
        thr, _ = compute_adaptive_threshold(stretches)
        self.assertEqual(thr, 9.5)

    def test_floor_when_no_cluster(self) -> None:
        thr, _ = compute_adaptive_threshold([4.1, 5.5])
        self.assertEqual(thr, config.EM6_BYBIT_ADAPT_FLOOR_PCT)


class TestPreEntryWatch(unittest.TestCase):
    def test_stable_after_20s(self) -> None:
        w = PreEntryWatch()
        t0 = 1_000_000
        self.assertFalse(w.tick(t0, 6.0))
        self.assertFalse(w.tick(t0 + 10_000, 6.0))
        self.assertFalse(w.tick(t0 + 15_000, 6.0))
        self.assertTrue(w.tick(t0 + 20_000, 6.0))

    def test_reset_on_new_peak(self) -> None:
        w = PreEntryWatch()
        t0 = 0
        w.tick(t0, 6.0)
        self.assertTrue(w.tick(t0 + 20_000, 6.0))
        self.assertFalse(w.tick(t0 + 30_000, 6.5))
        self.assertFalse(w.tick(t0 + 40_000, 6.5))
        self.assertTrue(w.tick(t0 + 55_000, 6.5))

    def test_cooldown_blocks(self) -> None:
        w = PreEntryWatch()
        t0 = 0
        w.start_cooldown(t0)
        self.assertEqual(w.phase(t0 + 1000), "cooldown_15s")
        self.assertFalse(w.tick(t0 + 20_000, 6.0))


class TestRegimeRecalc(unittest.TestCase):
    def test_scheduled_recalc(self) -> None:
        r = AdaptiveStretchRegime()
        r.update(0, [6.0, 6.1, 6.2])
        first = r.threshold_pct
        r.update(60_000, [8.0, 8.1, 8.2])
        self.assertEqual(first, r.threshold_pct)
        r.update(180_000, [8.0, 8.1, 8.2])
        self.assertGreaterEqual(r.threshold_pct, 8.0)


if __name__ == "__main__":
    unittest.main()
