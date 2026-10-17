"""БАБЛОСОС $$$: экстремум 5м своей 15м, вход на третьей свече."""

from __future__ import annotations

import config
from signal_engine.paper.detect import _check, grade_for
from signal_engine.paper.lh_scan_pivot import snapshot_pivot_levels
from signal_engine.paper.m5_htf import htf_pivot_setup, newest_pivot_reason
from signal_engine.state import SymbolState
from signal_engine.vacuum_lh import _meets_turnover

PYL_INTERVAL = config.PAPER_PYL_INTERVAL

PYL_MANDATORY = (
    "turnover_ok",
    "htf_15m",
    "htf_30m",
    "side_from_pivot",
)

PYL_CHECK_LABELS = {
    "turnover_ok": "Оборот 24ч ≥ порога LH-скана",
    "htf_15m": "Экстремум своей 15м и слабее предыдущей 15м",
    "htf_30m": "Нет пробоя high/low предыдущей 30м",
    "side_from_pivot": "Max → шорт, min → лонг",
}


def _htf_check_labels(interval: str) -> tuple[str, str]:
    if interval == "15":
        return ("1H слабее предыдущего", "без пробоя 4H")
    return ("15м слабее предыдущей", "без пробоя 30м")


def evaluate_htf_pivot_entry(
    state: SymbolState,
    now_ms: int,
    prev_snap: dict | None,
    interval: str,
    *,
    kind: str,
    variant: str | None = None,
) -> dict:
    """TZ-pivot (LH/HL) на interval + старший ТФ; kind — pyl / vps5 / vps15."""
    del prev_snap
    snap = snapshot_pivot_levels(state, interval, now_ms)
    turnover_ok = _meets_turnover(state)
    reason = newest_pivot_reason(state, now_ms, interval) if turnover_ok else "no_bar"
    signal = htf_pivot_setup(state, now_ms, interval) if reason == "ok" else None
    htf_mid, htf_outer = _htf_check_labels(interval)
    break_outer = "break_30m" if interval == "5" else "break_4h"
    missing_outer = "missing_30m" if interval == "5" else "missing_4h"
    mid_ok = reason in ("ok", break_outer, missing_outer)
    outer_ok = reason == "ok"
    side_ok = signal is not None and signal.get("side") in ("short", "long")

    checks = {
        "turnover_ok": _check(
            turnover_ok,
            "да" if turnover_ok else "нет",
            "оборот 24ч ≥ порога",
        ),
        "htf_15m": _check(
            mid_ok,
            signal.get("signal_key") if signal else reason,
            htf_mid,
        ),
        "htf_30m": _check(
            outer_ok,
            signal.get("pivot_price") if signal else reason,
            htf_outer,
        ),
        "side_from_pivot": _check(
            side_ok,
            signal.get("side") if signal else "—",
            "max → шорт, min → лонг",
        ),
    }
    failed = [k for k in PYL_MANDATORY if not checks[k]["ok"]]
    passed = not failed
    metrics: dict = {
        "bar_ts": int(signal["pivot_time_ms"]) if signal else None,
        "interval": interval,
        "pump": {
            "kind": kind,
            "side": signal.get("side") if signal else None,
            "trigger": f"{interval}m",
        },
    }
    if signal is not None:
        metrics.update(
            {
                "signal_key": signal["signal_key"],
                "pivot_time_ms": signal["pivot_time_ms"],
                "pivot_price": signal["pivot_price"],
                "pivot_kind": signal["pivot_kind"],
                "side": signal["side"],
                "pivot_high": float(signal["pivot_high"]),
                "pivot_low": float(signal["pivot_low"]),
            }
        )
    if snap:
        metrics["peaks"] = list(snap.get("peaks") or [])[-3:]
        metrics["troughs"] = list(snap.get("troughs") or [])[-3:]

    variants = [variant] if variant and passed else ([config.PAPER_PYL_VARIANT] if kind == "pyl" and passed else [])
    return {
        "checks": checks,
        "metrics": metrics,
        "score": 92.0 if passed else 25.0,
        "grade": grade_for(92.0 if passed else 25.0),
        "strict_btc": False,
        "passed": passed,
        "passed_count": len(PYL_MANDATORY) - len(failed),
        "failed": failed,
        "variants": variants,
        "entry_blocked": [],
        "side": signal.get("side") if passed else None,
    }


def evaluate_pyl(state: SymbolState, now_ms: int, prev_snap: dict | None = None) -> dict:
    return evaluate_htf_pivot_entry(
        state, now_ms, prev_snap, PYL_INTERVAL, kind="pyl", variant=config.PAPER_PYL_VARIANT
    )
