"""Аналитика тестовой BTC-стратегии."""

from __future__ import annotations

import unittest

from strategy_test.analytics import compute_analytics


class BtcAnalyticsTest(unittest.TestCase):
    def test_win_loss_factors(self) -> None:
        rows = [
            {
                "outcome": "WIN",
                "exit_ts": 1,
                "pnl_pct": 2.0,
                "grade": "A",
                "checks": {"m5_trigger": True, "vol_perp": True},
            },
            {
                "outcome": "LOSS",
                "exit_ts": 2,
                "pnl_pct": -1.0,
                "grade": "C",
                "checks": {"m5_trigger": True, "funding_perp": False},
            },
        ]
        stats = compute_analytics(rows)
        self.assertEqual(stats["closed"], 2)
        self.assertEqual(stats["wins"], 1)
        self.assertEqual(stats["factors_wins"]["m5_trigger"]["pct"], 100.0)
