"""Swing high/low на 1H и восходящая HH/HL-структура для lt20."""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from signal_engine.state import Bar
from signal_engine.swing_highs import closed_bars, pivot_highs_indexed


def pivot_lows_indexed(bars: list[Bar], wing: int) -> list[dict]:
    """Локальные минимумы по low (wing соседей с каждой стороны)."""
    if wing < 1 or len(bars) < wing * 2 + 1:
        return []
    out: list[dict] = []
    for i in range(wing, len(bars) - wing):
        low = float(bars[i].low)
        left = [float(bars[j].low) for j in range(i - wing, i)]
        right = [float(bars[j].low) for j in range(i + 1, i + wing + 1)]
        if low < min(left) and low < min(right):
            out.append({"time": int(bars[i].timestamp), "price": low, "bar_index": i})
    return out


def _inter_hh_low(bars: list[Bar], pivot_lows: list[dict], t_start: int, t_end: int) -> float | None:
    """Минимальный pivot-low или low баров между двумя HH (exclusive end)."""
    lows = [p["price"] for p in pivot_lows if t_start < p["time"] < t_end]
    if lows:
        return min(lows)
    seg = [b for b in bars if t_start < b.timestamp < t_end]
    if not seg:
        return None
    return min(b.low for b in seg)


def _ascending_hh_chain(pivots_in_window: list[dict], min_count: int, prefer_count: int) -> list[dict]:
    """Цепочка HH по времени: каждый следующий pivot выше предыдущего в цепочке."""
    if len(pivots_in_window) < min_count:
        return []
    chain: list[dict] = []
    for p in sorted(pivots_in_window, key=lambda x: x["time"]):
        if not chain or p["price"] > chain[-1]["price"] + 1e-12:
            chain.append(p)
    target = prefer_count if len(chain) >= prefer_count else min_count
    if len(chain) < target:
        return []
    return chain


@dataclass
class GrowthSwingStructure:
    valid: bool
    peak_price: float = 0.0
    peak_ts: int = 0
    anchor_price: float = 0.0
    anchor_ts: int = 0
    hh_chain: list[dict] = field(default_factory=list)
    inter_lows: list[float] = field(default_factory=list)
    higher_lows_ok: bool = False
    hh_hours_between: list[float | None] = field(default_factory=list)

    def to_metrics(self) -> dict:
        return {
            "hh_chain": [{"time": p["time"], "price": p["price"]} for p in self.hh_chain],
            "inter_lows": self.inter_lows,
            "higher_lows_ok": self.higher_lows_ok,
            "hh_hours_between": self.hh_hours_between,
        }


def analyze_growth_swing_1h(
    bars_1h: list[Bar],
    now_ms: int,
    last_price: float,
) -> GrowthSwingStructure:
    wing = config.PAPER_GROWTH_SWING_WING
    lookback = config.PAPER_GROWTH_SWING_LOOKBACK_BARS
    struct_ms = config.PAPER_GROWTH_STRUCTURE_HOURS * 3_600_000
    min_hh = config.PAPER_GROWTH_MIN_HH_COUNT
    prefer_hh = config.PAPER_GROWTH_PREFER_HH_COUNT

    closed = closed_bars(bars_1h, "60", now_ms)
    if len(closed) < wing * 2 + 3:
        return GrowthSwingStructure(valid=False)

    segment = closed[-lookback:] if len(closed) > lookback else closed
    window_start = now_ms - struct_ms
    pivots_hi = pivot_highs_indexed(segment, wing)
    pivots_lo = pivot_lows_indexed(segment, wing)

    in_window = [p for p in pivots_hi if p["time"] >= window_start]
    chain = _ascending_hh_chain(in_window, min_hh, prefer_hh)
    if len(chain) < min_hh:
        return GrowthSwingStructure(valid=False, hh_chain=chain)

    inter_lows: list[float] = []
    for i in range(len(chain) - 1):
        lo = _inter_hh_low(segment, pivots_lo, chain[i]["time"], chain[i + 1]["time"])
        if lo is None:
            return GrowthSwingStructure(valid=False, hh_chain=chain)
        inter_lows.append(lo)

    higher_lows_ok = all(
        inter_lows[i] > inter_lows[i - 1] + 1e-12 for i in range(1, len(inter_lows))
    ) if len(inter_lows) > 1 else True
    if not higher_lows_ok:
        return GrowthSwingStructure(
            valid=False,
            hh_chain=chain,
            inter_lows=inter_lows,
            higher_lows_ok=False,
        )

    peak = chain[-1]
    peak_price = float(peak["price"])
    peak_ts = int(peak["time"])

    anchor_price = peak_price
    anchor_ts = peak_ts
    after_peak = [p for p in pivots_lo if p["time"] > peak_ts]
    if after_peak:
        anchor = after_peak[-1]
        anchor_price = float(anchor["price"])
        anchor_ts = int(anchor["time"])
    else:
        seg_after = [b for b in segment if b.timestamp > peak_ts]
        if seg_after:
            low_bar = min(seg_after, key=lambda b: b.low)
            anchor_price = float(low_bar.low)
            anchor_ts = int(low_bar.timestamp)
        elif last_price < peak_price:
            anchor_price = min(last_price, peak_price)
            anchor_ts = now_ms

    hh_hours: list[float | None] = []
    for i in range(1, len(chain)):
        dt_h = (chain[i]["time"] - chain[i - 1]["time"]) / 3_600_000.0
        hh_hours.append(round(dt_h, 2))

    return GrowthSwingStructure(
        valid=True,
        peak_price=peak_price,
        peak_ts=peak_ts,
        anchor_price=anchor_price,
        anchor_ts=anchor_ts,
        hh_chain=chain,
        inter_lows=inter_lows,
        higher_lows_ok=True,
        hh_hours_between=hh_hours,
    )


def pullback_pct_from_peak(peak_price: float, last_price: float) -> float | None:
    if peak_price <= 0:
        return None
    return (peak_price - last_price) / peak_price * 100.0


def pullback_entry_ok(pullback_pct: float | None) -> bool:
    if pullback_pct is None:
        return False
    lo = config.PAPER_GROWTH_PULLBACK_MIN_PCT
    hi = config.PAPER_GROWTH_PULLBACK_MAX_PCT
    return lo <= pullback_pct <= hi
