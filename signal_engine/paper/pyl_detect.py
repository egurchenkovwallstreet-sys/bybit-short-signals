"""БАБЛОСОС $$$: lower high на 15m без пампа, вход в начале снижения после крупной вершины."""

from __future__ import annotations

import config
from signal_engine.paper.detect import MIN_MS, _check, _r, grade_for
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars, pivot_highs_indexed

PYL_MANDATORY = (
    "first_vertex",
    "lower_second",
    "major_second",
    "confirm_window",
    "confirm_close",
    "early_decline",
)

PYL_CHECK_LABELS = {
    "first_vertex": "Первая вершина V₁ — предыдущий pivot-high на 15m",
    "lower_second": "V₂ ниже V₁ по high (lower high)",
    "major_second": "V₂ — max high после V₁ (начало снижения, не отскок внизу)",
    "confirm_window": "Подтверждение на 1–3-й 15m после V₂",
    "confirm_close": "Close подтверждения < close V₂",
    "early_decline": "Откат от high V₂ до close ≤ лимита (не «на дне»)",
}


def _bars15(state: SymbolState) -> list[Bar]:
    raw = state.bars_htf.get("15") or []
    return [Bar(b.timestamp, b.open, b.high, b.low, b.close, b.volume) for b in raw]


def _major_second_since_v1(closed: list[Bar], v1_i: int, vi: int) -> bool:
    """V₂ — вершина начала отката: max high строго после V₁ достигается на V₂ (не микро-пик у дна)."""
    if vi <= v1_i:
        return False
    h2 = float(closed[vi].high)
    for j in range(v1_i + 1, vi + 1):
        if float(closed[j].high) > h2 + 1e-12:
            return False
    return True


def _pullback_from_vertex_high_pct(closed: list[Bar], vi: int, confirm_i: int) -> float | None:
    vh = float(closed[vi].high)
    if vh <= 0:
        return None
    return (vh - float(closed[confirm_i].close)) / vh * 100.0


def evaluate_pyl(state: SymbolState, now_ms: int) -> dict:
    bars = _bars15(state)
    closed = closed_bars(bars, "15", now_ms)
    lookback = config.PAPER_PYL_LOOKBACK_BARS
    if len(closed) > lookback:
        closed = closed[-lookback:]
    wing = config.PAPER_PYL_PIVOT_WING
    pivots = pivot_highs_indexed(closed, wing)
    confirm_i = len(closed) - 1
    confirm = closed[confirm_i] if confirm_i >= 0 else None
    max_pb = config.PAPER_PYL_MAX_PULLBACK_FROM_VERTEX_PCT
    allowed_offsets = config.PAPER_PYL_CONFIRM_OFFSETS

    match = None
    if confirm is not None and len(pivots) >= 2:
        for k in range(len(pivots) - 1, 0, -1):
            v2 = pivots[k]
            v1 = pivots[k - 1]
            vi = int(v2["bar_index"])
            v1_i = int(v1["bar_index"])
            if float(v2["price"]) >= float(v1["price"]) - 1e-12:
                continue
            if not _major_second_since_v1(closed, v1_i, vi):
                continue
            offset = confirm_i - vi
            if offset not in allowed_offsets:
                continue
            v2_bar = closed[vi]
            if confirm.close >= v2_bar.close - 1e-12:
                continue
            pb = _pullback_from_vertex_high_pct(closed, vi, confirm_i)
            if pb is None or pb > max_pb + 1e-9:
                continue
            match = {
                "v1": v1,
                "v2": v2,
                "offset": offset,
                "v2_bar": v2_bar,
                "pullback_pct": pb,
            }
            break

    checks = {
        "first_vertex": _check(
            match is not None,
            None if match is None else _r(float(match["v1"]["price"]), 6),
            "pivot V₁",
        ),
        "lower_second": _check(
            match is not None,
            None
            if match is None
            else {
                "first_high": _r(float(match["v1"]["price"]), 6),
                "second_high": _r(float(match["v2"]["price"]), 6),
            },
            "high(V₂) < high(V₁)",
        ),
        "major_second": _check(
            match is not None,
            None
            if match is None
            else _r(float(match["v2"]["price"]), 6),
            "max high после V₁ на баре V₂",
        ),
        "confirm_window": _check(
            match is not None,
            None if match is None else match["offset"],
            f"смещение {list(allowed_offsets)}",
        ),
        "confirm_close": _check(
            match is not None,
            None
            if match is None
            else {
                "confirm_close": _r(confirm.close, 6),
                "vertex_close": _r(match["v2_bar"].close, 6),
            },
            "close < close V₂",
        ),
        "early_decline": _check(
            match is not None,
            None if match is None else _r(match["pullback_pct"], 2),
            f"от high V₂ до close ≤ {max_pb}%",
        ),
    }
    failed = [k for k in PYL_MANDATORY if not checks[k]["ok"]]
    passed = not failed
    metrics = {
        "confirm_ts": int(confirm.timestamp) if confirm else None,
        "bar_ts": int(confirm.timestamp) if confirm else None,
        "pump": {
            "kind": "pyl",
            "side": "short",
            "trigger": "15m",
        },
    }
    if match:
        metrics["v1_ts"] = int(match["v1"]["time"])
        metrics["v2_ts"] = int(match["v2"]["time"])
        metrics["offset_bars"] = match["offset"]
        metrics["vertex_high"] = float(match["v2"]["price"])
        metrics["pullback_from_vertex_pct"] = match["pullback_pct"]
    return {
        "checks": checks,
        "metrics": metrics,
        "score": 90.0 if passed else 30.0,
        "grade": grade_for(90.0 if passed else 30.0),
        "strict_btc": False,
        "passed": passed,
        "passed_count": len(PYL_MANDATORY) - len(failed),
        "failed": failed,
        "variants": [config.PAPER_PYL_VARIANT] if passed else [],
        "entry_blocked": [],
        "side": "short" if passed else None,
    }
