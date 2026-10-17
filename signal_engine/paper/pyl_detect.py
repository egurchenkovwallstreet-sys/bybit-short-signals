"""БАБЛОСОС $$$: M5 pivot LH-скана; вход при подтверждении; стоп ±5% ROE от high/low свечи pivot."""

from __future__ import annotations

import config
from signal_engine.paper.detect import _check, _r, grade_for
from signal_engine.paper.lh_scan_pivot import (
    pivot_candle_bar,
    signal_from_pivot_diff,
    snapshot_pivot_levels,
)
from signal_engine.state import SymbolState

PYL_INTERVAL = config.PAPER_PYL_INTERVAL

PYL_MANDATORY = (
    "turnover_ok",
    "pivot_confirmed",
    "pivot_candle",
    "side_from_pivot",
)

PYL_CHECK_LABELS = {
    "turnover_ok": "Оборот 24ч ≥ порога LH-скана",
    "pivot_confirmed": "Pivot подтверждён (2 свечи справа, L15–L30, gap ≥30)",
    "pivot_candle": "Свеча pivot найдена (high/low для стопа)",
    "side_from_pivot": "Max → шорт, min → лонг",
}


def evaluate_pyl(state: SymbolState, now_ms: int, prev_snap: dict | None = None) -> dict:
    snap = snapshot_pivot_levels(state, PYL_INTERVAL, now_ms)
    signal = signal_from_pivot_diff(prev_snap, snap)
    pivot_bar = (
        pivot_candle_bar(state, PYL_INTERVAL, int(signal["pivot_time_ms"]), now_ms)
        if signal
        else None
    )
    turnover_ok = snap is not None
    confirmed = signal is not None
    has_bar = pivot_bar is not None
    side_ok = confirmed and signal.get("side") in ("short", "long")

    checks = {
        "turnover_ok": _check(
            turnover_ok,
            "да" if turnover_ok else "нет",
            "оборот 24ч ≥ порога",
        ),
        "pivot_confirmed": _check(
            confirmed,
            signal.get("signal_key") if signal else "—",
            "новый pivot 5m",
        ),
        "pivot_candle": _check(
            has_bar,
            None
            if pivot_bar is None
            else {"high": _r(pivot_bar.high, 6), "low": _r(pivot_bar.low, 6)},
            "high/low свечи pivot",
        ),
        "side_from_pivot": _check(
            side_ok,
            signal.get("side") if signal else "—",
            "max/min",
        ),
    }
    failed = [k for k in PYL_MANDATORY if not checks[k]["ok"]]
    passed = not failed
    metrics: dict = {
        "bar_ts": int(signal["pivot_time_ms"]) if signal else None,
        "pump": {
            "kind": "pyl",
            "side": signal.get("side") if signal else None,
            "trigger": f"{PYL_INTERVAL}m",
        },
    }
    if signal and pivot_bar is not None:
        metrics.update(
            {
                "signal_key": signal["signal_key"],
                "pivot_time_ms": signal["pivot_time_ms"],
                "pivot_price": signal["pivot_price"],
                "pivot_kind": signal["pivot_kind"],
                "side": signal["side"],
                "pivot_high": float(pivot_bar.high),
                "pivot_low": float(pivot_bar.low),
            }
        )
    if snap:
        metrics["peaks"] = list(snap.get("peaks") or [])[-3:]
        metrics["troughs"] = list(snap.get("troughs") or [])[-3:]

    return {
        "checks": checks,
        "metrics": metrics,
        "score": 92.0 if passed else 25.0,
        "grade": grade_for(92.0 if passed else 25.0),
        "strict_btc": False,
        "passed": passed,
        "passed_count": len(PYL_MANDATORY) - len(failed),
        "failed": failed,
        "variants": [config.PAPER_PYL_VARIANT] if passed else [],
        "entry_blocked": [],
        "side": signal.get("side") if passed else None,
    }
