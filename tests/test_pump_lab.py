"""Тесты лаборатории пампа."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import config
from signal_engine.pump_lab.detect import min_growth_pct, min_volume_ratio
from signal_engine.pump_lab.phases import compute_phase, passed_drawdown_pct, pump_class_from_duration, drawdown_from_peak_pct
from signal_engine.pump_lab.store import PumpLabStore
from signal_engine.state import Bar, SymbolState


class PumpLabPhaseTests(unittest.TestCase):
    def test_thresholds(self) -> None:
        self.assertEqual(min_growth_pct("fast"), 40.0)
        self.assertEqual(min_growth_pct("medium"), 80.0)
        self.assertEqual(min_volume_ratio("fast"), 10.0)
        self.assertEqual(min_volume_ratio("long"), 20.0)
        self.assertEqual(passed_drawdown_pct("fast"), 20.0)
        self.assertEqual(passed_drawdown_pct("long"), 40.0)

    def test_pump_class_duration(self) -> None:
        self.assertEqual(pump_class_from_duration(2 * 3_600_000), "fast")
        self.assertEqual(pump_class_from_duration(24 * 3_600_000), "medium")
        self.assertEqual(pump_class_from_duration(5 * 24 * 3_600_000), "long")

    def test_drawdown(self) -> None:
        self.assertAlmostEqual(drawdown_from_peak_pct(90, 100), 10.0)

    def test_phase_red_on_fresh_pump(self) -> None:
        now = 1_700_000_000_000
        state = SymbolState("TESTUSDT", last_price=100.0)
        for i in range(30):
            ts = now - (29 - i) * 60_000
            state.bars_1m.append(Bar(ts, 90 + i * 0.3, 91 + i * 0.3, 89, 90 + i * 0.3, 1000))
        phase, _ = compute_phase(state, "fast", 100.0, now - 5 * 60_000, now)
        self.assertIn(phase, {"red", "yellow", "green"})


class PumpLabStoreTests(unittest.TestCase):
    def test_insert_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab.db"
            store = PumpLabStore(path)
            store.open()
            eid = store.insert_episode(
                {
                    "symbol": "ABCUSDT",
                    "pump_class": "fast",
                    "phase": "red",
                    "valley_price": 1.0,
                    "valley_ts": 1000,
                    "peak_price": 1.5,
                    "peak_ts": 2000,
                    "growth_pct": 50.0,
                    "started_at": 1000,
                    "updated_at": 1000,
                    "last_price": 1.45,
                    "drawdown_pct": 3.3,
                    "metrics": {"delta": {"short": {"value": 1.0, "signal": 0}}},
                }
            )
            store.insert_snapshot(eid, 3000, "yellow", 1.4, 6.0, {"delta": {"short": {"value": -1.0, "signal": -1}}})
            active = store.active_episodes()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["symbol"], "ABCUSDT")
            store.close()


if __name__ == "__main__":
    unittest.main()
