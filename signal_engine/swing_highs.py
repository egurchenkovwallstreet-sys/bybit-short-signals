"""Pivot-максимумы и цепочка понижающихся вершин (только закрытые свечи)."""

from __future__ import annotations

from signal_engine.state import Bar

_INTERVAL_MS = {"15": 900_000, "30": 1_800_000, "60": 3_600_000, "240": 14_400_000, "D": 86_400_000}


def closed_bars(bars: list[Bar], interval: str, now_ms: int) -> list[Bar]:
    if not bars:
        return []
    step = _INTERVAL_MS.get(interval, 3_600_000)
    if len(bars) == 1:
        return bars if bars[0].timestamp + step <= now_ms else []
    out = [b for b in bars if b.timestamp + step <= now_ms]
    return out if out else bars[:-1]


def _bars_as_dicts(bars: list[Bar]) -> list[dict]:
    return [{"t": b.timestamp, "h": b.high, "l": b.low, "c": b.close} for b in bars]


def pivot_highs(bars: list[Bar], wing: int = 3) -> list[dict]:
    """Локальные максимумы по high (wing соседей с каждой стороны)."""
    rows = _bars_as_dicts(bars)
    n = wing
    if n < 1 or len(rows) < n * 2 + 1:
        return []
    out: list[dict] = []
    for i in range(n, len(rows) - n):
        high = float(rows[i]["h"])
        left = [float(rows[j]["h"]) for j in range(i - n, i)]
        right = [float(rows[j]["h"]) for j in range(i + 1, i + n + 1)]
        if high > max(left) and high > max(right):
            out.append({"time": int(rows[i]["t"]), "price": high})
    return out


def lower_high_chain_count(bars: list[Bar], pump_start_ts: int, interval: str, now_ms: int, wing: int = 3) -> int:
    """Число понижающихся pivot-high после абсолютного максимума с начала пампа."""
    segment = [b for b in closed_bars(bars, interval, now_ms) if b.timestamp >= pump_start_ts]
    peaks = pivot_highs(segment, wing)
    if len(peaks) < 2:
        return 0
    anchor_i = max(range(len(peaks)), key=lambda i: peaks[i]["price"])
    prev = peaks[anchor_i]["price"]
    chain = 0
    for peak in peaks[anchor_i + 1 :]:
        if peak["price"] < prev:
            chain += 1
            prev = peak["price"]
    return chain


def absolute_high_since(bars: list[Bar], pump_start_ts: int, interval: str, now_ms: int) -> tuple[float, int] | None:
    segment = [b for b in closed_bars(bars, interval, now_ms) if b.timestamp >= pump_start_ts]
    if not segment:
        return None
    best = max(segment, key=lambda b: b.high)
    return best.high, best.timestamp
