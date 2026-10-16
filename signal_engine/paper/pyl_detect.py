"""БАБЛОСОС $$$: lower high 15m; вход после двух медвежьих 15m подряд за V₂."""

from __future__ import annotations

import config
from signal_engine.paper.detect import _check, _r, grade_for
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars, pivot_highs_indexed

PYL_MANDATORY = (
    "first_vertex",
    "lower_second",
    "bearish_after_v2",
    "bearish_confirm",
    "decline_from_vertex",
)

PYL_CHECK_LABELS = {
    "first_vertex": "V₁ — предыдущая pivot-вершина 15m",
    "lower_second": "V₂ ниже V₁ по high (нижняя вершина)",
    "bearish_after_v2": "1-я 15m после V₂: close < open (снижение)",
    "bearish_confirm": "2-я 15m после V₂: close < open, затем вход",
    "decline_from_vertex": "Close входной свечи < close V₂",
}


def _bars15(state: SymbolState) -> list[Bar]:
    raw = state.bars_htf.get("15") or []
    return [Bar(b.timestamp, b.open, b.high, b.low, b.close, b.volume) for b in raw]


def _bearish(bar: Bar) -> bool:
    return float(bar.close) < float(bar.open) - 1e-12


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
    entry_offset = config.PAPER_PYL_ENTRY_OFFSET

    match = None
    bear1 = bear2 = None
    if confirm is not None and len(pivots) >= 2:
        for k in range(len(pivots) - 1, 0, -1):
            v2 = pivots[k]
            v1 = pivots[k - 1]
            vi = int(v2["bar_index"])
            if float(v2["price"]) >= float(v1["price"]) - 1e-12:
                continue
            if confirm_i != vi + entry_offset:
                continue
            v2_bar = closed[vi]
            b1 = closed[vi + 1]
            b2 = closed[vi + 2]
            if not _bearish(b1) or not _bearish(b2):
                continue
            if b2.timestamp != confirm.timestamp:
                continue
            if confirm.close >= v2_bar.close - 1e-12:
                continue
            match = {
                "v1": v1,
                "v2": v2,
                "offset": entry_offset,
                "v2_bar": v2_bar,
                "bear1": b1,
                "bear2": b2,
            }
            bear1, bear2 = b1, b2
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
        "bearish_after_v2": _check(
            bear1 is not None and _bearish(bear1),
            None
            if bear1 is None
            else {"open": _r(bear1.open, 6), "close": _r(bear1.close, 6)},
            "close < open",
        ),
        "bearish_confirm": _check(
            bear2 is not None and _bearish(bear2),
            None
            if bear2 is None
            else {"open": _r(bear2.open, 6), "close": _r(bear2.close, 6)},
            "close < open, вход после 2-й",
        ),
        "decline_from_vertex": _check(
            match is not None and confirm is not None,
            None
            if match is None or confirm is None
            else {
                "entry_close": _r(confirm.close, 6),
                "vertex_close": _r(match["v2_bar"].close, 6),
            },
            "close входа < close V₂",
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
