"""Пылесос: lower high на 15m без пампа, вход на 2–3-й свече после 2-й вершины."""

from __future__ import annotations

import config
from signal_engine.paper.detect import MIN_MS, _check, _r, grade_for
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars, pivot_highs_indexed

PYL_MANDATORY = (
    "first_vertex",
    "lower_second",
    "confirm_window",
    "confirm_close",
)

PYL_CHECK_LABELS = {
    "first_vertex": "Первая вершина — последний локальный хай на 15m",
    "lower_second": "Вторая вершина ниже первой (high)",
    "confirm_window": "Подтверждение на 2-й или 3-й 15m после 2-й вершины",
    "confirm_close": "Close подтверждения < close 2-й вершины",
}


def _bars15(state: SymbolState) -> list[Bar]:
    raw = state.bars_htf.get("15") or []
    return [Bar(b.timestamp, b.open, b.high, b.low, b.close, b.volume) for b in raw]


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

    match = None
    if confirm is not None and len(pivots) >= 2:
        for k in range(len(pivots) - 1, 0, -1):
            v2 = pivots[k]
            v1 = pivots[k - 1]
            vi = int(v2["bar_index"])
            if float(v2["price"]) >= float(v1["price"]) - 1e-12:
                continue
            offset = confirm_i - vi
            if offset not in config.PAPER_PYL_CONFIRM_OFFSETS:
                continue
            v2_bar = closed[vi]
            if confirm.close >= v2_bar.close - 1e-12:
                continue
            match = {"v1": v1, "v2": v2, "offset": offset, "v2_bar": v2_bar}
            break

    checks = {
        "first_vertex": _check(
            match is not None,
            None if match is None else _r(float(match["v1"]["price"]), 6),
            "локальный хай",
        ),
        "lower_second": _check(
            match is not None,
            None
            if match is None
            else {
                "first_high": _r(float(match["v1"]["price"]), 6),
                "second_high": _r(float(match["v2"]["price"]), 6),
            },
            "high₂ < high₁",
        ),
        "confirm_window": _check(
            match is not None,
            None if match is None else match["offset"],
            f"смещение {list(config.PAPER_PYL_CONFIRM_OFFSETS)}",
        ),
        "confirm_close": _check(
            match is not None,
            None
            if match is None
            else {
                "confirm_close": _r(confirm.close, 6),
                "vertex_close": _r(match["v2_bar"].close, 6),
            },
            "close < close 2-й вершины",
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
