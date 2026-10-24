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
    evaluate_reversal_short,
    is_purple_drawdown,
    lock_m15_peak_at_entry,
    raw_column,
    should_remove_pump_signal,
    _climax_from_bars,
    _ratchet_fixed_peak,
)
from signal_engine.watch_store import WatchRow
from signal_engine.pump_unified import EpisodeDraft
from signal_engine.state import Bar
from signal_engine.state import Bar, SymbolState


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
        self.assertFalse(is_purple_drawdown(8.0))
        self.assertTrue(is_purple_drawdown(15.0))
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

    def test_remove_at_50pct_drawdown(self) -> None:
        st = SymbolState("X")
        st.last_price = 49.0
        self.assertTrue(should_remove_pump_signal(st, 100.0))
        st.last_price = 51.0
        self.assertFalse(should_remove_pump_signal(st, 100.0))

    def test_lock_m15_peak_at_entry(self) -> None:
        st = SymbolState("BTCUSDT")
        t0 = 1_700_000_000_000
        bars = [
            Bar(t0, 1.0, 1.1, 0.9, 1.0, 100),
            Bar(t0 + 900_000, 1.0, 1.5, 0.95, 1.4, 200),
            Bar(t0 + 1_800_000, 1.4, 1.6, 1.3, 1.55, 150),
        ]
        st.bars_htf["15"] = bars
        draft = EpisodeDraft(
            symbol="BTCUSDT",
            valley_price=0.9,
            valley_ts=t0,
            peak_price=1.5,
            peak_ts=t0 + 900_000,
            growth_pct=50.0,
            pump_class="fast",
            volume_ratio=5.0,
            source="bars_15m",
        )
        p, ts = lock_m15_peak_at_entry(st, draft, t0 + 1_900_000)
        self.assertAlmostEqual(p, 1.6)
        self.assertEqual(ts, t0 + 1_800_000)

    def test_lock_prefers_episode_peak_over_local_15m(self) -> None:
        st = SymbolState("IRYSUSDT")
        t0 = 1_700_000_000_000
        st.bars_htf["15"] = [
            Bar(t0, 0.05, 0.067, 0.05, 0.057, 100),
        ]
        st.bars_htf["60"] = [
            Bar(t0 - 3_600_000, 0.01, 0.53, 0.01, 0.5, 1000),
            Bar(t0, 0.05, 0.06, 0.05, 0.057, 100),
        ]
        draft = EpisodeDraft(
            symbol="IRYSUSDT",
            valley_price=0.01,
            valley_ts=t0 - 7_200_000,
            peak_price=0.535,
            peak_ts=t0 - 3_600_000,
            growth_pct=5000.0,
            pump_class="long",
            volume_ratio=50.0,
            source="valley_7d_1h",
        )
        p, _ = lock_m15_peak_at_entry(st, draft, t0)
        self.assertGreaterEqual(p, 0.53)

    def test_ratchet_peak_on_new_15m_high(self) -> None:
        t0 = 1_700_000_000_000
        st = SymbolState("ANIMEUSDT")
        st.bars_htf["15"] = [
            Bar(t0, 0.003, 0.0036, 0.0029, 0.0035, 100),
            Bar(t0 + 900_000, 0.0035, 0.0042, 0.0034, 0.0040, 200),
        ]
        watch = WatchRow(
            board="pump_signals",
            symbol="ANIMEUSDT",
            entered_at=t0,
            dismissed=False,
            confirmed_stage=1,
            pending_stage=None,
            pending_since=None,
            meta={"valley_ts": t0 - 3_600_000, "m15_peak_price": 0.0036, "m15_peak_ts": t0},
        )
        now = t0 + 1_800_000
        p, ts = _ratchet_fixed_peak(watch, st, now, 0.0036, t0)
        self.assertAlmostEqual(p, 0.0042)
        self.assertEqual(ts, t0 + 900_000)

    def test_reversal_short_ok(self) -> None:
        rev = evaluate_reversal_short(
            trigger="1h",
            since_peak=90.0,
            drawdown=6.0,
            minutes_no_high=70.0,
            oi_1h_pct=-1.2,
            climax={"peak_vol_x": 8.0, "range_vs_atr": 3.5, "upper_wick_pct": 4.0, "two_lower_highs": True},
            oi_into_peak_pct=5.0,
        )
        self.assertTrue(rev["ok"])

    def test_reversal_rejects_7d_and_missing_climax(self) -> None:
        rev = evaluate_reversal_short(
            trigger="7d",
            since_peak=90.0,
            drawdown=6.0,
            minutes_no_high=70.0,
            oi_1h_pct=-1.2,
            climax={"peak_vol_x": None, "range_vs_atr": None, "upper_wick_pct": None, "two_lower_highs": False},
            oi_into_peak_pct=None,
        )
        self.assertFalse(rev["ok"])
        self.assertIn("trigger", rev["failed"])
        self.assertIn("peak_vol", rev["failed"])

    def test_climax_two_lower_highs(self) -> None:
        t0 = 1_700_000_000_000
        hour = 3_600_000
        bars = []
        for i in range(26):
            ts = t0 + i * hour
            vol = 10.0 if i != 23 else 80.0
            high = 1.0 + i * 0.01 if i <= 23 else 1.23 - (i - 23) * 0.03
            bars.append(Bar(ts, high - 0.01, high, high - 0.02, high - 0.015, vol))
        peak_ts = t0 + 23 * hour
        out = _climax_from_bars(bars, peak_ts, 24)
        self.assertGreaterEqual(out["peak_vol_x"], 5)
        self.assertTrue(out["two_lower_highs"])


if __name__ == "__main__":
    unittest.main()
