"""Pivot-максимумы и цепочка понижающихся вершин (только закрытые свечи)."""

from __future__ import annotations

from dataclasses import dataclass

import config
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
    return [
        {"time": p["time"], "price": p["price"]}
        for p in pivot_highs_indexed(bars, wing)
    ]


def pivot_highs_indexed(bars: list[Bar], wing: int = 3) -> list[dict]:
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
            out.append({"time": int(rows[i]["t"]), "price": high, "bar_index": i})
    return out


def loose_pivot_highs_indexed(bars: list[Bar]) -> list[dict]:
    """Мягче: high не ниже соседей слева/справа (wing=1, допуск равенства)."""
    rows = _bars_as_dicts(bars)
    if len(rows) < 5:
        return []
    out: list[dict] = []
    for i in range(1, len(rows) - 1):
        high = float(rows[i]["h"])
        if high >= float(rows[i - 1]["h"]) and high >= float(rows[i + 1]["h"]):
            if out and out[-1]["bar_index"] == i - 1 and out[-1]["price"] == high:
                continue
            out.append({"time": int(rows[i]["t"]), "price": high, "bar_index": i})
    merged: list[dict] = []
    for p in out:
        if merged and p["bar_index"] - merged[-1]["bar_index"] <= 1:
            if p["price"] >= merged[-1]["price"]:
                merged[-1] = p
            continue
        merged.append(p)
    return merged


@dataclass(frozen=True)
class TwoPeakMatch:
    kind: str  # lower_high | double_top | marginal_hh
    interval: str
    first_price: float
    second_price: float
    bars_between: int
    first_time: int
    second_time: int


def _peak_pair_kind(first_price: float, second_price: float) -> str | None:
    if first_price <= 0:
        return None
    tol = config.X2_RETRACE_PEAK_EQUAL_TOLERANCE_PCT / 100.0
    max_above = config.X2_RETRACE_MAX_SECOND_PEAK_ABOVE_PCT / 100.0
    diff = (second_price - first_price) / first_price
    if diff > max_above:
        return None
    if abs(diff) <= tol:
        return "double_top"
    if second_price < first_price:
        return "lower_high"
    if diff <= max_above:
        return "marginal_hh"
    return None


def _peaks_for_segment(segment: list[Bar], wing: int) -> list[dict]:
    peaks = pivot_highs_indexed(segment, wing)
    if len(peaks) >= 2:
        return peaks
    loose = loose_pivot_highs_indexed(segment)
    return loose if len(loose) >= 2 else peaks


def _segment_for_peaks(bars: list[Bar], pump_start_ts: int, interval: str, now_ms: int) -> list[Bar]:
    closed = closed_bars(bars, interval, now_ms)
    lookback_ms = config.X2_RETRACE_LOOKBACK_DAYS * 24 * 3600 * 1000
    window_start = now_ms - lookback_ms
    start = min(pump_start_ts, window_start)
    return [b for b in closed if b.timestamp >= start]


def _match_from_peaks(
    peaks: list[dict],
    interval: str,
    min_between: int,
) -> TwoPeakMatch | None:
    best: TwoPeakMatch | None = None
    best_score = -1.0
    for a in range(len(peaks) - 1):
        for b in range(a + 1, len(peaks)):
            p1, p2 = peaks[a], peaks[b]
            between = int(p2["bar_index"]) - int(p1["bar_index"]) - 1
            if between < min_between:
                continue
            kind = _peak_pair_kind(float(p1["price"]), float(p2["price"]))
            if kind is None:
                continue
            score = float(p1["price"]) + float(p2["price"]) + between * 0.001
            if score >= best_score:
                best_score = score
                best = TwoPeakMatch(
                    kind=kind,
                    interval=interval,
                    first_price=float(p1["price"]),
                    second_price=float(p2["price"]),
                    bars_between=between,
                    first_time=int(p1["time"]),
                    second_time=int(p2["time"]),
                )
    return best


def find_two_peak_match(
    bars: list[Bar],
    pump_start_ts: int,
    interval: str,
    now_ms: int,
    wing: int | None = None,
) -> TwoPeakMatch | None:
    segment = _segment_for_peaks(bars, pump_start_ts, interval, now_ms)
    if len(segment) < config.X2_RETRACE_MIN_BARS:
        return None
    min_between = config.X2_RETRACE_MIN_BARS_BETWEEN_PEAKS
    wings = [wing if wing is not None else config.X2_RETRACE_PIVOT_WING]
    if wings[0] > 1:
        wings.append(1)
    for w in wings:
        peaks = _peaks_for_segment(segment, w)
        found = _match_from_peaks(peaks, interval, min_between)
        if found is not None:
            return found
    return None


def find_two_peak_htf(
    bars_1h: list[Bar],
    bars_4h: list[Bar],
    pump_start_ts: int,
    now_ms: int,
) -> TwoPeakMatch | None:
    for interval, bars in (("240", bars_4h), ("60", bars_1h)):
        match = find_two_peak_match(bars, pump_start_ts, interval, now_ms)
        if match is not None:
            return match
    return None


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
