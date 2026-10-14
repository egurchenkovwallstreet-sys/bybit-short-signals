"""Unit-тесты swing HH/HL 1H и отката входа lt20."""

import unittest

import config
from signal_engine.paper.growth_detect import evaluate_growth, find_growth
from signal_engine.paper.swing_1h import (
    analyze_growth_swing_1h,
    pivot_lows_indexed,
    pullback_entry_ok,
    pullback_pct_from_peak,
)
from signal_engine.swing_highs import pivot_highs_indexed
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState

HOUR = 3_600_000
NOW = (1_800_000_000_000 // HOUR) * HOUR
WING = config.PAPER_GROWTH_SWING_WING


def _bar(i: int, o: float, h: float, lo: float, c: float) -> Bar:
    return Bar(NOW - (24 - i) * HOUR, o, h, lo, c, 1000.0)


def ascending_hh_bars() -> list[Bar]:
    """Три HH за 12 ч с HL между (wing=2), последний пик 130."""
    bars: list[Bar] = []
    for i in range(25):
        bars.append(_bar(i, 100, 101, 99, 100))
    # pivot highs ~ i=7 @110, i=13 @120, i=19 @130
    for idx, peak in ((7, 110), (13, 120), (19, 130)):
        for j in range(max(0, idx - 3), min(25, idx + 4)):
            if j == idx:
                bars[j] = _bar(j, peak - 1, peak, peak - 2, peak - 0.5)
            elif abs(j - idx) <= 2:
                bars[j] = _bar(j, 100, 100 + abs(j - idx), 98, 99)
    # pullback lows between HH (соседи выше low, иначе wing=2 не видит pivot)
    for idx, lo in ((10, 105), (16, 112)):
        for j in range(idx - 2, idx + 3):
            if j == idx:
                bars[j] = _bar(j, lo + 1, lo + 3, lo, lo + 0.5)
            elif 0 <= j < 25:
                bars[j] = _bar(j, lo + 4, lo + 6, lo + 2, lo + 3)
    return bars


class Swing1HTest(unittest.TestCase):
    def test_pivot_highs_lows_synthetic(self) -> None:
        bars = ascending_hh_bars()
        hi = pivot_highs_indexed(bars, WING)
        lo = pivot_lows_indexed(bars, WING)
        self.assertGreaterEqual(len(hi), 2)
        self.assertGreaterEqual(len(lo), 1)
        prices = [p["price"] for p in hi]
        self.assertIn(130, prices)
        self.assertGreater(max(prices), 120)

    def test_ascending_structure_valid(self) -> None:
        bars = ascending_hh_bars()
        struct = analyze_growth_swing_1h(bars, NOW, 126.1)
        self.assertTrue(struct.valid)
        self.assertGreaterEqual(len(struct.hh_chain), config.PAPER_GROWTH_MIN_HH_COUNT)
        self.assertTrue(struct.higher_lows_ok)
        self.assertAlmostEqual(struct.peak_price, 130.0)

    def test_pullback_entry_band(self) -> None:
        peak = 130.0
        self.assertFalse(pullback_entry_ok(pullback_pct_from_peak(peak, 129.5)))  # ~0.4%
        self.assertTrue(pullback_entry_ok(pullback_pct_from_peak(peak, 126.1)))  # ~3%
        self.assertTrue(pullback_entry_ok(pullback_pct_from_peak(peak, 121.0)))  # ~6.9%
        self.assertFalse(pullback_entry_ok(pullback_pct_from_peak(peak, 118.0)))  # ~9.2%

    def test_find_growth_needs_structure(self) -> None:
        state = SymbolState("GUSDT")
        state.last_price = 126.1
        state.bars_1m = [Bar(NOW - HOUR, 126, 127, 125, 126, 5000) for _ in range(500)]
        klines = {"60": ascending_hh_bars()}
        g = find_growth(state, None, NOW, klines)
        self.assertIsNotNone(g)
        self.assertAlmostEqual(g.peak_price, 130.0)

    def test_evaluate_turbo_needs_pullback_and_ema(self) -> None:
        state = SymbolState("GUSDT")
        state.last_price = 129.8  # ~0.15% откат — не вход
        state.bars_1m = []
        for h in range(10):
            ts = NOW - h * HOUR
            vol = 3000 if h < 4 else 1000
            state.bars_1m.append(Bar(ts, 128, 129, 127, 128, vol))
        state.oi_5m = [(NOW - i * 300_000, 1000 + i * 10) for i in range(50)]
        klines = {"60": ascending_hh_bars()}
        g = find_growth(state, None, NOW, klines)
        self.assertIsNotNone(g)
        tape = SymbolTape()
        for _ in range(60):
            tape.add_trade(NOW, "Buy", 5000)
            tape.add_trade(NOW, "Sell", 1000)
        ev = evaluate_growth(state, tape, g, klines, NOW)
        self.assertFalse(ev.checks["pullback_entry"]["ok"])
        self.assertFalse(ev.passed)


if __name__ == "__main__":
    unittest.main()
