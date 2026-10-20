"""EMA60 stretch: детектор и ступени стопа."""

from __future__ import annotations

import unittest

import config
from signal_engine.paper.ema60_stretch_detect import evaluate_ema60_stretch, stretch_passes_variant
from signal_engine.paper.position import Position, ema60_stretch_trail_stop
from signal_engine.paper.position import price_for_long_roe, price_for_roe
from signal_engine.paper.position import net_roe_stop_price, net_roe_stop_price_long
from signal_engine.state import Bar, SymbolState


def _bars_from_closes(closes: list[float], step_ms: int = 300_000) -> list[Bar]:
    t0 = 1_700_000_000_000
    return [
        Bar(
            timestamp=t0 + i * step_ms,
            open=c,
            high=c * 1.001,
            low=c * 0.999,
            close=c,
            volume=1.0,
            from_kline=True,
        )
        for i, c in enumerate(closes)
    ]


def _state_at_stretch(price: float, trend_step: float) -> tuple[SymbolState, int]:
    closes = [100.0 + i * trend_step for i in range(150)]
    state = SymbolState(symbol="XUSDT")
    state.bars_htf["5"] = _bars_from_closes(closes)
    state.last_price = price
    now_ms = state.bars_htf["5"][-1].timestamp + 300_000
    return state, now_ms


class Ema60StretchDetectTest(unittest.TestCase):
    def test_short_when_price_above_ema(self) -> None:
        state, now_ms = _state_at_stretch(0.0, 0.15)
        from signal_engine.paper.ma333_regime import ma333_regime_detail

        ema = float(ma333_regime_detail(state, now_ms, "short")["ema60"])
        state.last_price = ema * 1.08
        ev = evaluate_ema60_stretch(state, now_ms)
        self.assertTrue(ev.passed)
        self.assertEqual(ev.side, "short")
        self.assertAlmostEqual(float(ev.metrics["stretch_pct"]), 8.0, places=1)
        self.assertIn(config.PAPER_EM6_VARIANT, ev.variants())
        self.assertIn(config.PAPER_EM8_VARIANT, ev.variants())
        self.assertNotIn(config.PAPER_EM10_VARIANT, ev.variants())
        self.assertTrue(stretch_passes_variant(ev, config.PAPER_EM8_VARIANT))

    def test_long_when_price_below_ema(self) -> None:
        state, now_ms = _state_at_stretch(0.0, -0.15)
        from signal_engine.paper.ma333_regime import ma333_regime_detail

        ema = float(ma333_regime_detail(state, now_ms, "long")["ema60"])
        state.last_price = ema * 0.93
        ev = evaluate_ema60_stretch(state, now_ms)
        self.assertEqual(ev.side, "long")
        self.assertTrue(stretch_passes_variant(ev, config.PAPER_EM6_VARIANT))

    def test_fails_inside_band(self) -> None:
        state, now_ms = _state_at_stretch(0.0, 0.15)
        from signal_engine.paper.ma333_regime import ma333_regime_detail

        ema = float(ma333_regime_detail(state, now_ms, "short")["ema60"])
        state.last_price = ema * 1.02
        ev = evaluate_ema60_stretch(state, now_ms)
        self.assertFalse(ev.passed)


class Ema60StretchStopTest(unittest.TestCase):
    def test_short_stop_ladder(self) -> None:
        entry = 1.0
        margin = 50.0
        fee = entry * 10 * config.PAPER_FEE_RATE_TAKER
        lev = config.PAPER_LEVERAGE
        initial = ema60_stretch_trail_stop(entry, 1.0, lev, margin=margin, entry_fee=fee, side="short")
        self.assertAlmostEqual(
            initial,
            net_roe_stop_price(entry, margin, -15.0, lev, fee, 0.0),
            places=6,
        )
        best = entry * (1.0 - 0.05 / lev)
        at5 = ema60_stretch_trail_stop(entry, best, lev, margin=margin, entry_fee=fee, side="short")
        self.assertLess(at5, entry)
        best10 = entry * (1.0 - 0.12 / lev)
        at10 = ema60_stretch_trail_stop(entry, best10, lev, margin=margin, entry_fee=fee, side="short")
        trail = price_for_roe(entry, 12.0 - 5.0, lev)
        self.assertLessEqual(at10, trail + 1e-9)

    def test_long_stop_ladder(self) -> None:
        entry = 1.0
        margin = 50.0
        fee = entry * 10 * config.PAPER_FEE_RATE_TAKER
        lev = config.PAPER_LEVERAGE
        best = entry * (1.0 + 0.12 / lev)
        stop = ema60_stretch_trail_stop(entry, best, lev, margin=margin, entry_fee=fee, side="long")
        trail = price_for_long_roe(entry, 7.0, lev)
        self.assertGreaterEqual(stop, trail - 1e-9)

    def test_position_sync_uses_ema_stretch(self) -> None:
        pos = Position(
            symbol="X",
            opened_at=0,
            entry_price=1.0,
            margin=50.0,
            side="short",
            stop_style="ema_stretch",
        )
        self.assertGreater(pos.stop_price, 1.0)


if __name__ == "__main__":
    unittest.main()
