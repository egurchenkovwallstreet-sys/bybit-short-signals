"""БАБЛОСОС / Пылесос 5: LH/HL L15–L30 на 5m; Пылесос 15 — + HTF на 15m."""

from __future__ import annotations

import config
from signal_engine.paper.detect import _check, grade_for
from signal_engine.paper.lh_scan_pivot import snapshot_pivot_levels
from signal_engine.paper.m5_htf import htf_pivot_setup, newest_pivot_reason
from signal_engine.state import SymbolState
from signal_engine.vacuum_lh import _meets_turnover

PYL_INTERVAL = config.PAPER_PYL_INTERVAL

PYL_MANDATORY_5 = (
    "turnover_ok",
    "pivot_left",
    "side_from_pivot",
)

PYL_MANDATORY_15 = (
    "turnover_ok",
    "htf_15m",
    "htf_30m",
    "side_from_pivot",
)

# API / UI для баблососа (5m)
PYL_MANDATORY = PYL_MANDATORY_5

PYL_CHECK_LABELS = {
    "turnover_ok": "Оборот 24ч ≥ порога LH-скана",
    "pivot_left": "Сила слева L15–L30 (left_strength)",
    "htf_15m": "Экстремум 1H и слабее предыдущего 1H (15m TF)",
    "htf_30m": "Нет пробоя high/low 4H (15m TF)",
    "side_from_pivot": "LH → шорт, HL → лонг",
}


def mandatory_for_interval(interval: str) -> tuple[str, ...]:
    return PYL_MANDATORY_5 if interval == "5" else PYL_MANDATORY_15


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
    del prev_snap
    snap = snapshot_pivot_levels(state, interval, now_ms)
    turnover_ok = _meets_turnover(state)
    mandatory = mandatory_for_interval(interval)
    reason = newest_pivot_reason(state, now_ms, interval) if turnover_ok else "no_bar"
    signal = htf_pivot_setup(state, now_ms, interval) if turnover_ok else None
    side_ok = signal is not None and signal.get("side") in ("short", "long")
    ls = int(signal.get("left_strength") or 0) if signal else 0

    if interval == "5":
        checks = {
            "turnover_ok": _check(
                turnover_ok,
                "да" if turnover_ok else "нет",
                "оборот 24ч ≥ порога",
            ),
            "pivot_left": _check(
                side_ok and ls >= config.VACUUM_LH_PIVOT_LEFT,
                f"L{ls}" if ls else reason,
                f"L{config.VACUUM_LH_PIVOT_LEFT}–L{config.VACUUM_LH_PIVOT_LEFT_MAX} слева",
            ),
            "side_from_pivot": _check(
                side_ok,
                signal.get("side") if signal else "—",
                "LH → шорт, HL → лонг",
            ),
        }
    else:
        htf_mid, htf_outer = _htf_check_labels(interval)
        break_outer = "break_4h"
        missing_outer = "missing_4h"
        mid_ok = reason in ("ok", break_outer, missing_outer)
        outer_ok = reason == "ok"
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

    failed = [k for k in mandatory if not checks[k]["ok"]]
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
                "left_strength": ls,
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
        "passed_count": len(mandatory) - len(failed),
        "failed": failed,
        "variants": variants,
        "entry_blocked": [],
        "side": signal.get("side") if passed else None,
    }


def evaluate_pyl(state: SymbolState, now_ms: int, prev_snap: dict | None = None) -> dict:
    return evaluate_htf_pivot_entry(
        state, now_ms, prev_snap, PYL_INTERVAL, kind="pyl", variant=config.PAPER_PYL_VARIANT
    )
