"""Пылесос: M5 — максимум A, минимум C, второй максимум B < A; вход после 2 медвежьих (B и +1)."""

from __future__ import annotations

import config
from signal_engine.paper.detect import _check, _r, grade_for
from signal_engine.paper.vacuum_senior_gate import vacuum_senior_allows_entry
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars, pivot_highs_indexed

VAC_MANDATORY = (
    "structure_acb",
    "bearish_at_b",
    "bearish_after_b",
    "senior_tf_trend",
)

VAC_CHECK_LABELS = {
    "structure_acb": "A (max) → C (min) → B (max), B ниже A",
    "bearish_at_b": "Свеча B закрылась медвежьей (close < open)",
    "bearish_after_b": "Следующая после B — тоже медвежья, вход на её close",
    "senior_tf_trend": "15m: LH↓ для шорта (2 pivot, mixed→3)",
}


def _bars5(state: SymbolState) -> list[Bar]:
    return list(state.bars_htf.get("5") or [])


def _bearish(bar: Bar) -> bool:
    return float(bar.close) < float(bar.open) - 1e-12


def _find_acb(closed: list[Bar], confirm_i: int, wing: int) -> dict | None:
    highs = pivot_highs_indexed(closed, wing)
    if len(highs) < 2:
        return None

    for b in reversed(highs):
        bi = int(b["bar_index"])
        bp = float(b["price"])
        if confirm_i != bi + 1:
            continue
        b_bar = closed[bi]

        for a in reversed(highs):
            ai = int(a["bar_index"])
            if ai >= bi:
                continue
            ap = float(a["price"])
            if ap <= bp + 1e-12:
                continue
            if bi - ai < 2:
                continue
            ci = min(range(ai + 1, bi), key=lambda j: float(closed[j].low))
            cp = float(closed[ci].low)
            return {
                "a": a,
                "c": {"time": int(closed[ci].timestamp), "price": cp, "bar_index": ci},
                "b": b,
                "a_i": ai,
                "c_i": ci,
                "b_i": bi,
                "b_bar": b_bar,
            }
    return None


def evaluate_vac(state: SymbolState, now_ms: int) -> dict:
    bars = _bars5(state)
    closed = closed_bars(bars, "5", now_ms)
    lookback = config.PAPER_VAC_LOOKBACK_BARS
    if len(closed) > lookback:
        closed = closed[-lookback:]
    wing = config.PAPER_VAC_SWING_WING
    confirm_i = len(closed) - 1
    confirm = closed[confirm_i] if confirm_i >= 0 else None

    struct = None
    if len(closed) >= wing * 2 + 5 and confirm is not None:
        struct = _find_acb(closed, confirm_i, wing)

    b_bar = struct["b_bar"] if struct else None
    bear_b = b_bar is not None and _bearish(b_bar)
    bear_after = confirm is not None and _bearish(confirm)

    checks = {
        "structure_acb": _check(
            struct is not None,
            None
            if not struct
            else {
                "A_high": _r(float(struct["a"]["price"]), 6),
                "C_low": _r(float(struct["c"]["price"]), 6),
                "B_high": _r(float(struct["b"]["price"]), 6),
            },
            "B < A, C между",
        ),
        "bearish_at_b": _check(
            bear_b,
            None
            if b_bar is None
            else {"open": _r(b_bar.open, 6), "close": _r(b_bar.close, 6)},
            "close < open на B",
        ),
        "bearish_after_b": _check(
            struct is not None and bear_after,
            None
            if confirm is None
            else {"open": _r(confirm.open, 6), "close": _r(confirm.close, 6)},
            "close < open на свече после B",
        ),
    }

    senior_ok, senior_detail = vacuum_senior_allows_entry(state, now_ms, "5", "short")
    checks["senior_tf_trend"] = _check(
        senior_ok,
        senior_detail,
        VAC_CHECK_LABELS["senior_tf_trend"],
    )

    failed = [k for k in VAC_MANDATORY if not checks[k]["ok"]]
    passed = not failed
    metrics: dict = {
        "confirm_ts": int(confirm.timestamp) if confirm else None,
        "bar_ts": int(confirm.timestamp) if confirm else None,
        "pump": {"kind": "vac", "side": "short", "trigger": "5m"},
    }
    if struct:
        metrics.update(
            {
                "a_ts": int(struct["a"]["time"]),
                "b_ts": int(struct["b"]["time"]),
                "c_ts": int(struct["c"]["time"]),
            }
        )

    return {
        "checks": checks,
        "metrics": metrics,
        "score": 92.0 if passed else 28.0,
        "grade": grade_for(92.0 if passed else 28.0),
        "strict_btc": False,
        "passed": passed,
        "passed_count": len(VAC_MANDATORY) - len(failed),
        "failed": failed,
        "variants": [config.PAPER_VAC_VARIANT] if passed else [],
        "entry_blocked": [],
        "side": "short" if passed else None,
    }
