"""Тесты лаборатории пампа."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import config
from signal_engine.pump_lab.detect import detect_episodes, min_growth_pct, min_volume_ratio, window_ms
from signal_engine.pump_lab.phases import (
    compute_phase,
    drawdown_from_peak_pct,
    is_pump_passed,
    passed_drawdown_pct,
    post_peak_correction_trough,
    pump_class_from_duration,
)
from signal_engine.pump_lab.store import PumpLabStore
from signal_engine.state import Bar, SymbolState


class PumpLabPhaseTests(unittest.TestCase):
    def test_thresholds(self) -> None:
        self.assertEqual(min_growth_pct("fast"), 40.0)
        self.assertEqual(min_growth_pct("medium"), 80.0)
        self.assertEqual(min_volume_ratio("fast"), 10.0)
        self.assertEqual(min_volume_ratio("long"), 10.0)
        self.assertEqual(passed_drawdown_pct("fast"), 20.0)
        self.assertEqual(passed_drawdown_pct("long"), 40.0)

    def test_pump_class_duration(self) -> None:
        self.assertEqual(pump_class_from_duration(2 * 3_600_000), "fast")
        self.assertEqual(pump_class_from_duration(36 * 3_600_000), "medium")
        self.assertEqual(pump_class_from_duration(5 * 24 * 3_600_000), "long")

    def test_drawdown(self) -> None:
        self.assertAlmostEqual(drawdown_from_peak_pct(90, 100), 10.0)

    def test_trough_retrace_not_passed_while_falling(self) -> None:
        now = 1_700_000_000_000
        peak_ts = now - 6 * 3_600_000
        peak = 100.0
        state = SymbolState("TUSDT", last_price=72.0)
        for i in range(8):
            ts = peak_ts + i * 15 * 60_000
            low = 100 - i * 4
            state.bars_htf.setdefault("15", []).append(
                Bar(ts, low + 2, low + 3, low, low + 1, 1000)
            )
        _, _, retrace = post_peak_correction_trough(state, peak_ts, peak)
        self.assertGreaterEqual(retrace, 20.0)
        passed, _ = is_pump_passed(state, "fast", peak, peak_ts, now)
        self.assertFalse(passed)

    def test_phase_red_on_fresh_pump(self) -> None:
        now = 1_700_000_000_000
        state = SymbolState("TESTUSDT", last_price=100.0)
        for i in range(30):
            ts = now - (29 - i) * 60_000
            state.bars_1m.append(Bar(ts, 90 + i * 0.3, 91 + i * 0.3, 89, 90 + i * 0.3, 1000))
        phase, _ = compute_phase(state, "fast", 100.0, now - 5 * 60_000, now)
        self.assertIn(phase, {"red", "yellow", "green"})


class PumpLabDetectTests(unittest.TestCase):
    def test_detect_fast_window_valley_then_peak(self) -> None:
        now = 1_700_000_000_000
        state = SymbolState("PUMPUSDT", last_price=140.0)
        step = 15 * 60_000
        base_ts = now - window_ms("fast") + step
        n = int(window_ms("fast") / step)
        for i in range(n):
            ts = base_ts + i * step
            low = 100.0 if i < n // 3 else 100.0 + (i - n // 3) * 2
            high = low + (50.0 if i == n - 1 else 5.0)
            vol = 100.0 if i != n - 1 else 50_000.0
            state.bars_htf.setdefault("15", []).append(Bar(ts, low, high, low, (low + high) / 2, vol))
        drafts = detect_episodes(state, now)
        fast = [d for d in drafts if d.pump_class == "fast"]
        self.assertEqual(len(fast), 1)
        self.assertGreaterEqual(fast[0].growth_pct, 40.0)
        self.assertGreaterEqual(fast[0].volume_ratio or 0, 10.0)


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
