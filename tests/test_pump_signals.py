"""Доска «Памп сигналы» — классификация колонок."""

from __future__ import annotations

import unittest

from signal_engine.evaluate import Reading
from signal_engine.paper.detect import MANDATORY
from signal_engine.pump_signals import (
    COLUMN_GREEN,
    COLUMN_PURPLE,
    COLUMN_RED,
    COLUMN_YELLOW,
    is_purple_drawdown,
    raw_column,
    should_remove_pump_signal,
)
from signal_engine.state import SymbolState


def _checks(**flags: bool) -> dict:
    out = {k: {"ok": False} for k in MANDATORY}
    for k, v in flags.items():
        out[k] = {"ok": v}
    return out


class PumpSignalsColumnTests(unittest.TestCase):
    def test_green_when_confluence(self) -> None:
        col = raw_column(
            checks={k: {"ok": True} for k in MANDATORY},
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

    def test_purple_drawdown_band(self) -> None:
        self.assertFalse(is_purple_drawdown(15.0))
        self.assertTrue(is_purple_drawdown(20.0))
        self.assertFalse(is_purple_drawdown(70.0))

    def test_purple_column(self) -> None:
        col = raw_column(
            checks={k: {"ok": False} for k in MANDATORY},
            metrics={"since_peak_min": 120, "drawdown_from_peak_pct": 25.0, "pump": {}},
            reading=Reading(),
            weaken=1,
            drawdown=25.0,
            since_peak=120.0,
            minutes_no_high=60.0,
        )
        self.assertEqual(col, COLUMN_PURPLE)

    def test_no_purple_while_new_highs(self) -> None:
        col = raw_column(
            checks={k: {"ok": False} for k in MANDATORY},
            metrics={"since_peak_min": 120, "drawdown_from_peak_pct": 25.0, "pump": {}},
            reading=Reading(),
            weaken=1,
            drawdown=25.0,
            since_peak=120.0,
            minutes_no_high=5.0,
        )
        self.assertNotEqual(col, COLUMN_PURPLE)

    def test_no_purple_low_drawdown_active(self) -> None:
        col = raw_column(
            checks=_checks(stall=False),
            metrics={"since_peak_min": 10, "drawdown_from_peak_pct": 5.0, "pump": {}},
            reading=Reading(),
            weaken=0,
            drawdown=5.0,
            since_peak=10.0,
            minutes_no_high=2.0,
        )
        self.assertEqual(col, COLUMN_RED)

    def test_remove_at_70(self) -> None:
        st = SymbolState("X")
        st.last_price = 30.0
        self.assertTrue(should_remove_pump_signal(st, 100.0))


if __name__ == "__main__":
    unittest.main()
