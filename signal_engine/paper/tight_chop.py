"""Узкий боковик на 5m: отсечение «топтания» перед входом (стратегия 333)."""

from __future__ import annotations

import config
from signal_engine.state import Bar, SymbolState


def _closed_bars_before(bars: list[Bar], now_ms: int) -> list[Bar]:
    out: list[Bar] = []
    for b in bars or []:
        ts = int(b.timestamp)
        if ts + 300_000 <= int(now_ms):
            out.append(b)
    return out


def tight_chop_detail(state: SymbolState, now_ms: int, interval: str = "5") -> dict:
    """Метрики коробки; insufficient_data=True если баров мало — вход не блокируем."""
    window = int(config.PAPER_CHOP_WINDOW_BARS)
    raw = list(state.bars_htf.get(interval) or [])
    closed = _closed_bars_before(raw, now_ms)
    ref = float(state.last_price or (closed[-1].close if closed else 0) or 0)
    if ref <= 0:
        return {"insufficient_data": True, "tight": False}
    if len(closed) < config.PAPER_CHOP_MIN_BARS:
        return {"insufficient_data": True, "tight": False, "bars": len(closed)}
    slice_bars = closed[-window:]
    hi = max(b.high for b in slice_bars)
    lo = min(b.low for b in slice_bars)
    range_pct = (hi - lo) / ref * 100.0
    bar_ranges = [(b.high - b.low) / ref * 100.0 for b in slice_bars]
    avg_bar_pct = sum(bar_ranges) / len(bar_ranges) if bar_ranges else 0.0
    ratio = range_pct / avg_bar_pct if avg_bar_pct > 1e-12 else 0.0
    wide_floor = float(config.PAPER_CHOP_MIN_WIDE_RANGE_PCT)
    tight_range = float(config.PAPER_CHOP_TIGHT_RANGE_PCT)
    tight_ratio = float(config.PAPER_CHOP_TIGHT_BAR_RATIO)
    tight = False
    if range_pct >= wide_floor:
        tight = False
    elif range_pct <= tight_range:
        tight = True
    elif ratio <= tight_ratio and range_pct < wide_floor:
        tight = True
    return {
        "insufficient_data": False,
        "tight": tight,
        "range_pct": round(range_pct, 3),
        "avg_bar_pct": round(avg_bar_pct, 3),
        "range_bar_ratio": round(ratio, 2),
        "bars": len(slice_bars),
        "wide_floor_pct": wide_floor,
    }


def is_tight_chop(state: SymbolState, now_ms: int, interval: str = "5") -> tuple[bool, str]:
    d = tight_chop_detail(state, now_ms, interval)
    if d.get("insufficient_data"):
        return False, "мало баров — фильтр пропущен"
    if d.get("tight"):
        return True, (
            f"узко: range {d['range_pct']:.2f}% "
            f"(≤{config.PAPER_CHOP_TIGHT_RANGE_PCT:g}% или ratio {d['range_bar_ratio']:.1f})"
        )
    return False, f"range {d['range_pct']:.2f}% (широкий ≥{d['wide_floor_pct']:.1f}% или норма)"
