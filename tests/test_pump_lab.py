"""Тесты лаборатории пампа."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import config
from signal_engine.pump_lab.detect import (
    detect_episodes,
    min_growth_pct,
    min_volume_ratio,
    volume_ratio_min_to_peak,
    window_ms,
)
from signal_engine.pump_lab.phases import (
    compute_phase,
    drawdown_from_peak_pct,
    is_pump_passed,
    passed_drawdown_pct,
    post_peak_correction_trough,
    pump_class_from_duration,
)
from signal_engine.pump_lab.lab import PumpLab
from signal_engine.pump_lab.store import PumpLabStore
from signal_engine.pump_lab.study import STUDY_FIELDS, build_study
from signal_engine.state import Bar, SymbolState


class PumpLabPhaseTests(unittest.TestCase):
    def test_thresholds(self) -> None:
        self.assertEqual(min_growth_pct("fast"), 40.0)
        self.assertEqual(min_growth_pct("medium"), 60.0)
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
    def test_volume_ratio_symmetric_sums(self) -> None:
        step = 15 * 60_000
        valley_ts = 1_000_000
        peak_ts = valley_ts + step
        bars = [
            Bar(valley_ts - step, 1, 1, 1, 1, 100.0),
            Bar(valley_ts, 1, 1, 1, 1, 1000.0),
            Bar(peak_ts, 1, 1, 1, 1, 1000.0),
        ]
        ratio = volume_ratio_min_to_peak(bars, valley_ts, peak_ts, window_start_ms=0)
        self.assertAlmostEqual(ratio or 0, 20.0)

    def test_detect_fast_window_valley_then_peak(self) -> None:
        now = 1_700_000_000_000
        state = SymbolState("PUMPUSDT", last_price=140.0)
        step = 15 * 60_000
        base_ts = now - window_ms("fast") + step
        n = int(window_ms("fast") / step)
        valley_i = n - 4
        for i in range(n):
            ts = base_ts + i * step
            if i < valley_i:
                low, high = 110.0, 112.0
            elif i == valley_i:
                low, high = 100.0, 104.0
            else:
                low = 100.0 + (i - valley_i) * 3
                high = low + (40.0 if i == n - 1 else 4.0)
            vol = 50.0 if i < valley_i else (600.0 if valley_i <= i <= n - 1 else 50.0)
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

    def test_study_marks_survive_sample_trim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PumpLabStore(Path(tmp) / "lab.db")
            store.open()
            eid = store.insert_episode(
                {
                    "symbol": "ABCUSDT",
                    "pump_class": "fast",
                    "phase": "yellow",
                    "peak_price": 1.5,
                    "peak_ts": 1,
                    "started_at": 1,
                    "updated_at": 1,
                }
            )
            store.insert_study(eid, 1, "peak", "red", 1.5, {"price": 1.5})
            store.insert_study(eid, 2, "stall", "yellow", 1.4, {"price": 1.4})
            for i in range(501):
                store.insert_study(eid, 100 + i, "sample", "yellow", 1.4, {"price": 1.4})
            marks = {row["mark"] for row in store.study_marks(eid)}
            self.assertEqual(marks, {"peak", "stall", "sample"})
            kept = store.conn.execute(
                "SELECT COUNT(*) FROM lab_study WHERE episode_id = ? AND mark = 'sample'",
                (eid,),
            ).fetchone()[0]
            self.assertEqual(kept, 500)
            store.close()


class OrderBookStateTests(unittest.TestCase):
    def test_reset_delta_and_delete(self) -> None:
        state = SymbolState("BEAMUSDT")
        state.ingest(
            {
                "type": "orderbook",
                "timestamp": 1000,
                "data": {
                    "reset": True,
                    "bids": [[100.0, 2.0], [99.0, 1.0]],
                    "asks": [[101.0, 3.0]],
                },
            }
        )
        state.ingest(
            {
                "type": "orderbook",
                "timestamp": 2000,
                "data": {"bids": [[100.0, 0.0], [98.0, 4.0]], "asks": [[101.0, 1.0]]},
            }
        )
        self.assertNotIn(100.0, state.book_bids)
        self.assertEqual(state.book_bids[99.0], 1.0)
        self.assertEqual(state.book_bids[98.0], 4.0)
        self.assertEqual(state.book_asks[101.0], 1.0)
        self.assertEqual(state.book_ts, 2000)
        state.ingest(
            {
                "type": "ticker",
                "timestamp": 2000,
                "data": {"mark_price": "101", "index_price": "100", "bid1_price": "99.5", "ask1_price": "100.5"},
            }
        )
        self.assertEqual(state.mark_price, 101.0)
        self.assertEqual(state.index_price, 100.0)


class PumpStudyTests(unittest.TestCase):
    def test_build_study_records_raw_numbers(self) -> None:
        now = 1_700_000_000_000
        state = SymbolState("LABUSDT")
        for i in range(40):
            ts = now - (39 - i) * 60_000
            close = 110.0 - i * 0.25
            state.bars_1m.append(Bar(ts, close + 0.1, close + 0.2, close - 0.1, close, 10.0))
        state.last_price = state.bars_1m[-1].close
        state.funding_rate = 0.0008
        state.mark_price = 100.4
        state.index_price = 100.0
        for i in range(15):
            minute = now - i * 60_000
            state.taker_buy[minute] = 2.0
            state.taker_sell[minute] = 8.0
        state.oi_5m = [(now - 60 * 60_000, 1000.0), (now - 15 * 60_000, 900.0), (now, 800.0)]
        minute = (now // 60_000) * 60_000
        state.liq_notional[minute] = 5000.0
        state.liq_long_notional[minute] = 1000.0
        state.book_bids = {99.9: 200.0, 99.0: 50.0}
        state.book_asks = {100.1: 10.0}
        btc = SymbolState("BTCUSDT", last_price=100.0)
        for i in range(20):
            ts = now - (19 - i) * 60_000
            btc.bars_1m.append(Bar(ts, 100.0, 100.0, 100.0, 100.0, 1.0))
        features = build_study(state, btc, 110.0, now - 10 * 60_000, now, 50.0)
        self.assertEqual(set(features), {key for key, _ in STUDY_FIELDS})
        self.assertIsNone(features["long_account_ratio"])
        self.assertIsNone(features["rush_orders"])
        self.assertAlmostEqual(features["since_peak_min"], 10.0)
        self.assertGreater(features["drawdown_pct"], 0)
        self.assertEqual(features["sell_windows_over_50"], 3.0)
        self.assertEqual(features["short_liq_5m_usd"], 5000.0)
        self.assertEqual(features["long_liq_5m_usd"], 1000.0)
        self.assertEqual(features["price_down_oi_down"], 1.0)
        self.assertLess(features["cvd_15m_usd"], 0)
        self.assertGreater(features["spread_pct"], 0)
        self.assertIsNotNone(features["sell_slip_10k_pct"])
        self.assertAlmostEqual(features["premium_pct"], 0.4)
        self.assertEqual(features["lower_closes"], 39.0)

    def test_snapshot_writes_marks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PumpLabStore(Path(tmp) / "lab.db")
            store.open()
            lab = PumpLab(store)
            state = SymbolState("ABCUSDT", last_price=1.4)
            lab._snapshot(7, 3000, "yellow", state, {}, ["sample", "peak", "stall"], None, 1.5, 2000, 50.0)
            marks = {row["mark"] for row in store.study_marks(7)}
            self.assertEqual(marks, {"sample", "peak", "stall"})
            peak = next(row for row in store.study_marks(7) if row["mark"] == "peak")
            self.assertIn("price", peak["features"])
            self.assertEqual(len(peak["features"]), len(STUDY_FIELDS))
            store.close()

    def test_tracked_card_is_sampled_when_pump_is_not_redetected(self) -> None:
        now = 1_700_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            store = PumpLabStore(Path(tmp) / "lab.db")
            store.open()
            eid = store.insert_episode(
                {
                    "symbol": "LABUSDT",
                    "pump_class": "fast",
                    "phase": "red",
                    "valley_price": 50.0,
                    "valley_ts": now - 30 * 60_000,
                    "peak_price": 100.0,
                    "peak_ts": now - 10 * 60_000,
                    "growth_pct": 100.0,
                    "started_at": now - 20 * 60_000,
                    "updated_at": now - 20 * 60_000,
                    "last_price": 100.0,
                }
            )
            state = SymbolState("LABUSDT", last_price=97.0)
            state.bars_1m.append(Bar(now - 60_000, 98, 99, 96, 97, 10))
            PumpLab(store)._run({"LABUSDT": state}, now)
            marks = {row["mark"] for row in store.study_marks(eid)}
            self.assertIn("sample", marks)
            fresh = store.episode(eid)
            self.assertEqual(fresh["status"], "active")
            self.assertEqual(fresh["updated_at"], now)
            store.close()


if __name__ == "__main__":
    unittest.main()
