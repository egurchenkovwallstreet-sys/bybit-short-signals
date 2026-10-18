"""Шлюз старшего TF для вкладки Пылесос."""

from __future__ import annotations

import unittest

from signal_engine.paper.vacuum_senior_gate import (
    _confirms_down,
    _confirms_up,
    senior_interval_for_entry,
)


class VacuumSeniorGateTest(unittest.TestCase):
    def test_ladder(self) -> None:
        self.assertEqual(senior_interval_for_entry("5"), "15")
        self.assertEqual(senior_interval_for_entry("15"), "30")
        self.assertEqual(senior_interval_for_entry("30"), "60")
        self.assertIsNone(senior_interval_for_entry("60"))
        self.assertIsNone(senior_interval_for_entry("240"))

    def test_two_peaks_down(self) -> None:
        self.assertTrue(_confirms_down([100.0, 90.0]))
        self.assertFalse(_confirms_down([90.0, 100.0]))

    def test_three_on_mixed_two(self) -> None:
        self.assertTrue(_confirms_down([100.0, 95.0, 90.0]))
        self.assertTrue(_confirms_down([100.0, 95.0, 92.0]))
        self.assertFalse(_confirms_down([100.0, 105.0]))

    def test_two_troughs_up(self) -> None:
        self.assertTrue(_confirms_up([10.0, 12.0]))
        self.assertTrue(_confirms_up([10.0, 11.0, 13.0]))


if __name__ == "__main__":
    unittest.main()
