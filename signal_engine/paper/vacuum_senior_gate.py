"""Шлюз вкладки «Пылесос»: старший TF подтверждает сторону (2 pivot, при mixed — 3).

Лестница: 5m→15m, 15m→30m, 30m→1H; 1H/4H — без шлюза.
Не перебитый pivot: ≥5 свечей после confirm без пробоя уровня и отход ≥0.1%.
"""

from __future__ import annotations

import config
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import (
    closed_bars,
    filter_pivots_min_bar_gap,
    pivot_highs_floating_left,
    pivot_lows_floating_left,
)

VACUUM_ENTRY_TO_SENIOR: dict[str, str] = {
    "5": "15",
    "15": "30",
    "30": "60",
}

_AWAY_PCT = 0.001
_POST_CONFIRM_BARS = 5


def senior_interval_for_entry(entry_interval: str) -> str | None:
    return VACUUM_ENTRY_TO_SENIOR.get(str(entry_interval))


def _pivot_unbroken(segment: list[Bar], pivot: dict, kind: str) -> bool:
    bi = int(pivot.get("bar_index", -1))
    if bi < 0:
        return False
    confirm = config.VACUUM_LH_PIVOT_RIGHT
    post_start = bi + confirm + 1
    if post_start + _POST_CONFIRM_BARS > len(segment):
        return False
    price = float(pivot["price"])
    away = False
    for j in range(post_start, post_start + _POST_CONFIRM_BARS):
        b = segment[j]
        if kind == "peak":
            if float(b.high) > price + 1e-12:
                return False
            if float(b.low) <= price * (1.0 - _AWAY_PCT):
                away = True
        else:
            if float(b.low) < price - 1e-12:
                return False
            if float(b.high) >= price * (1.0 + _AWAY_PCT):
                away = True
    return away


def _left_ok(p: dict) -> bool:
    ls = int(p.get("left_strength") or 0)
    lo = config.VACUUM_LH_PIVOT_LEFT
    hi = config.VACUUM_LH_PIVOT_LEFT_MAX
    return lo <= ls <= hi


def _unbroken_pivots(segment: list[Bar], kind: str) -> list[dict]:
    lo = config.VACUUM_LH_PIVOT_LEFT
    hi = config.VACUUM_LH_PIVOT_LEFT_MAX
    pr = config.VACUUM_LH_PIVOT_RIGHT
    gap = config.VACUUM_LH_PIVOT_MIN_GAP
    if kind == "peak":
        raw = pivot_highs_floating_left(segment, lo, hi, pr)
        filtered = filter_pivots_min_bar_gap(raw, gap, kind="peak")
    else:
        raw = pivot_lows_floating_left(segment, lo, hi, pr)
        filtered = filter_pivots_min_bar_gap(raw, gap, kind="trough")
    out: list[dict] = []
    for p in filtered:
        if not _left_ok(p):
            continue
        if _pivot_unbroken(segment, p, kind):
            out.append(p)
    out.sort(key=lambda x: int(x["time"]))
    return out


def _confirms_down(prices: list[float]) -> bool:
    if len(prices) < 2:
        return False
    if prices[-1] < prices[-2]:
        return True
    if len(prices) >= 3:
        a, b, c = prices[-3], prices[-2], prices[-1]
        return c < b < a
    return False


def _confirms_up(prices: list[float]) -> bool:
    if len(prices) < 2:
        return False
    if prices[-1] > prices[-2]:
        return True
    if len(prices) >= 3:
        a, b, c = prices[-3], prices[-2], prices[-1]
        return c > b > a
    return False


def vacuum_senior_allows_entry(
    state: SymbolState,
    now_ms: int,
    entry_interval: str,
    side: str,
) -> tuple[bool, str]:
    """short — LH↓ на старшем TF; long — HL↑. Без старшего TF — пропуск (True)."""
    htf = senior_interval_for_entry(entry_interval)
    if htf is None:
        return True, "старший TF не требуется"
    if side not in ("short", "long"):
        return False, "нет стороны"

    bars = closed_bars(state.bars_htf.get(htf) or [], htf, now_ms)
    if len(bars) < 40:
        return False, f"мало {htf}m баров"

    if side == "short":
        pivots = _unbroken_pivots(bars, "peak")
        prices = [float(p["price"]) for p in pivots]
        if not _confirms_down(prices):
            tail = prices[-3:] if len(prices) >= 3 else prices
            return False, f"{htf}m LH: {tail} (нужны ↓)"
        tail = prices[-3:] if len(prices) >= 3 and not (prices[-1] < prices[-2]) else prices[-2:]
        return True, f"{htf}m LH ↓ {' → '.join(f'{x:g}' for x in tail)}"

    pivots = _unbroken_pivots(bars, "trough")
    prices = [float(p["price"]) for p in pivots]
    if not _confirms_up(prices):
        tail = prices[-3:] if len(prices) >= 3 else prices
        return False, f"{htf}m HL: {tail} (нужны ↑)"
    tail = prices[-3:] if len(prices) >= 3 and not (prices[-1] > prices[-2]) else prices[-2:]
    return True, f"{htf}m HL ↑ {' → '.join(f'{x:g}' for x in tail)}"
