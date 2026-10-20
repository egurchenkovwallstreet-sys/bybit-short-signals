"""t20/p10 tri-gate and pump floor scale."""
from __future__ import annotations

import unittest

import config
from signal_engine.paper.detect import paper_entry_blocks, paper_t20_p10_mandatory_checks, paper_t20_p10_tri_blocks


class TriGateTest(unittest.TestCase):
    def test_stall_ok_never_blocks(self) -> None:
        metrics = {"since_peak_min": 200, "drawdown_from_peak_pct": 15, "pump": {"trigger": "7d"}}
        checks = {"stall": {"ok": True}}
        self.assertEqual(paper_t20_p10_tri_blocks(metrics, checks), [])

    def test_late_without_stall(self) -> None:
        metrics = {"since_peak_min": 91, "drawdown_from_peak_pct": 8, "pump": {"trigger": "4h"}}
        checks = {"stall": {"ok": False}}
        self.assertEqual(paper_t20_p10_tri_blocks(metrics, checks), ["tri_no_stall"])

    def test_7d_without_stall(self) -> None:
        metrics = {"since_peak_min": 30, "drawdown_from_peak_pct": 5, "pump": {"trigger": "7d"}}
        checks = {"stall": {"ok": False}}
        self.assertEqual(paper_t20_p10_tri_blocks(metrics, checks), ["tri_no_stall"])

    def test_deep_dd_without_stall(self) -> None:
        metrics = {"since_peak_min": 40, "drawdown_from_peak_pct": 11.5, "pump": {"trigger": "24h"}}
        checks = {"stall": {"ok": False}}
        self.assertEqual(paper_t20_p10_tri_blocks(metrics, checks), ["tri_no_stall"])

    def test_no_stall_but_early_shallow_4h_ok(self) -> None:
        metrics = {"since_peak_min": 40, "drawdown_from_peak_pct": 10, "pump": {"trigger": "4h"}}
        checks = {"stall": {"ok": False}}
        self.assertEqual(paper_t20_p10_tri_blocks(metrics, checks), [])

    def test_pump_floor_scale_default(self) -> None:
        self.assertAlmostEqual(config.PAPER_PUMP_FLOOR_SCALE, 0.8)

    def test_mandatory_stall_and_oi(self) -> None:
        self.assertIn("need_stall", paper_t20_p10_mandatory_checks({"stall": {"ok": False}}))
        self.assertIn("need_oi_down", paper_t20_p10_mandatory_checks({"oi_1h_negative": {"ok": False}}))
        self.assertEqual(
            paper_t20_p10_mandatory_checks({"stall": {"ok": True}, "oi_1h_negative": {"ok": True}}),
            [],
        )

    def test_no_7d_in_entry_gate(self) -> None:
        base = {"pump": {"trigger": "4h", "volume_ratio": 10}, "since_peak_min": 30, "drawdown_from_peak_pct": 5}
        self.assertNotIn("no_7d", paper_entry_blocks(base))
        self.assertIn("no_7d", paper_entry_blocks({**base, "pump": {"trigger": "7d", "volume_ratio": 10}}))


if __name__ == "__main__":
    unittest.main()
