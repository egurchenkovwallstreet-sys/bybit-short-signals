"""p10g/p10q/p10m — вход как в прогоне E02/E07/E10."""

from __future__ import annotations

import unittest

import config
from signal_engine.paper.detect import Evaluation, paper_p10_sim_qualifies


def _ev(passed_count: int, metrics: dict, checks: dict | None = None) -> Evaluation:
    return Evaluation(
        checks=checks or {},
        metrics=metrics,
        score=10.0,
        score_parts={},
        strict_btc=False,
    )


class P10SimQualifyTest(unittest.TestCase):
    def test_gate_only_passes_p10g(self) -> None:
        m = {
            "since_peak_min": 30.0,
            "drawdown_from_peak_pct": 5.0,
            "pump": {"trigger": "4h", "volume_ratio": 10.0},
        }
        ev = _ev(3, m)
        self.assertTrue(paper_p10_sim_qualifies(config.PAPER_P10G_VARIANT, ev))
        self.assertFalse(paper_p10_sim_qualifies(config.PAPER_P10Q_VARIANT, ev))

    def test_five_of_nine_for_p10q(self) -> None:
        m = {
            "since_peak_min": 30.0,
            "drawdown_from_peak_pct": 5.0,
            "pump": {"trigger": "4h", "volume_ratio": 10.0},
        }
        ev = _ev(5, m)
        self.assertTrue(paper_p10_sim_qualifies(config.PAPER_P10Q_VARIANT, ev))


if __name__ == "__main__":
    unittest.main()
