"""Единое правило pivot (paper + LH-скан): L15–L30 слева, 2 справа, разнос ≥ gap 30.

Источник якорей: vacuum_lh.all_anchor_peaks / all_anchor_troughs (VACUUM_LH_PIVOT_*).
"""

from __future__ import annotations

from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars
from signal_engine.vacuum_lh import (
    _bars_for_interval,
    _meets_turnover,
    _min_bars,
    all_anchor_peaks,
    all_anchor_troughs,
)


M5_STEP_MS = 300_000


def pivot_has_two_right_bars(index: dict[int, Bar], pivot_ts: int, step: int = M5_STEP_MS) -> bool:
    ts = int(pivot_ts)
    return index.get(ts + step) is not None and index.get(ts + 2 * step) is not None


def snapshot_pivot_levels(state: SymbolState, interval: str, now_ms: int) -> dict | None:
    if not _meets_turnover(state):
        return None
    bars = _bars_for_interval(state, interval)
    if len(bars) < _min_bars(interval):
        return None
    peaks = all_anchor_peaks(bars, interval, now_ms)
    troughs = all_anchor_troughs(bars, interval, now_ms)
    return {"interval": interval, "peaks": peaks, "troughs": troughs}


def pivot_keys(points: list[dict]) -> frozenset[tuple[int, float]]:
    out: set[tuple[int, float]] = set()
    for p in points:
        t = int(p.get("time_ms") or p.get("time") or 0)
        out.add((t, round(float(p["price"]), 8)))
    return frozenset(out)


def _pack_signal(t_ms: int, side: str, key: tuple[int, float], price: float) -> dict:
    return {
        "side": side,
        "signal_key": f"{side}:{key[0]}:{key[1]}",
        "pivot_time_ms": t_ms,
        "pivot_price": price,
        "pivot_kind": "peak" if side == "short" else "trough",
    }


def signal_from_pivot_diff(prev: dict | None, cur: dict | None) -> dict | None:
    """Новый pivot в снимке (момент подтверждения после PIVOT_RIGHT свечей)."""
    if not cur:
        return None
    prev_norm = prev or {"peaks": [], "troughs": []}
    new_peaks = pivot_keys(cur.get("peaks") or []) - pivot_keys(prev_norm.get("peaks") or [])
    new_troughs = pivot_keys(cur.get("troughs") or []) - pivot_keys(prev_norm.get("troughs") or [])
    if not new_peaks and not new_troughs:
        return None
    events: list[tuple[int, str, tuple[int, float], float]] = []
    for key in new_peaks:
        events.append((key[0], "short", key, float(key[1])))
    for key in new_troughs:
        events.append((key[0], "long", key, float(key[1])))
    events.sort(key=lambda x: x[0])
    t_ms, side, key, price = events[-1]
    return _pack_signal(t_ms, side, key, price)


def pivot_candle_bar(state: SymbolState, interval: str, pivot_time_ms: int, now_ms: int) -> Bar | None:
    bars = closed_bars(_bars_for_interval(state, interval), interval, now_ms)
    t = int(pivot_time_ms)
    for b in bars:
        if int(b.timestamp) == t:
            return b
    return None
