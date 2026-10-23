"""Доска «Памп сигналы» — классификация колонок."""

from __future__ import annotations

import unittest

from signal_engine.evaluate import Reading
from signal_engine.paper.detect import MANDATORY
from signal_engine.pump_signals import COLUMN_GREEN, COLUMN_RED, COLUMN_YELLOW, raw_column


def _checks(**flags: bool) -> dict:
    out = {k: {"ok": False} for k in MANDATORY}
    for k, v in flags.items():
        out[k] = {"ok": v}
    return out


class PumpSignalsColumnTests(unittest.TestCase):
    def test_green_when_confluence(self) -> None:
        col = raw_column(
            checks=_checks(
                stall=True,
                oi_1h_negative=True,
                sells_dominate=True,
                buys_faded=True,
                volume_fade=True,
                short_liq_faded=True,
            ),
            metrics={
                "since_peak_min": 60,
                "drawdown_from_peak_pct": 8.0,
                "pump": {"trigger": "4h", "volume_ratio": 12},
            },
            reading=Reading(cvd_divergence=True, taker_ratio=0.8),
            weaken=4,
            drawdown=8.0,
            since_peak=60.0,
            minutes_no_high=45.0,
        )
        self.assertEqual(col, COLUMN_GREEN)

    def test_red_early_pump(self) -> None:
        col = raw_column(
            checks=_checks(stall=False),
            metrics={"since_peak_min": 10, "drawdown_from_peak_pct": 1.0, "pump": {}},
            reading=Reading(oi_change_1h_pct=2.0),
            weaken=0,
            drawdown=1.0,
            since_peak=10.0,
            minutes_no_high=5.0,
        )
        self.assertEqual(col, COLUMN_RED)

    def test_yellow_fading(self) -> None:
        col = raw_column(
            checks=_checks(stall=True, oi_1h_negative=False),
            metrics={
                "since_peak_min": 50,
                "drawdown_from_peak_pct": 6.0,
                "pump": {"trigger": "24h"},
            },
            reading=Reading(),
            weaken=2,
            drawdown=6.0,
            since_peak=50.0,
            minutes_no_high=30.0,
        )
        self.assertEqual(col, COLUMN_YELLOW)


if __name__ == "__main__":
    unittest.main()
