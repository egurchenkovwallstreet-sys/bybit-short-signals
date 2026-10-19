"""БАБЛОСОС / Пылесос 5: LH/HL L15–L30 на 5m; Пылесос 15 — + HTF на 15m."""

from __future__ import annotations

import config
from signal_engine.paper.detect import _check, grade_for
from signal_engine.paper.lh_scan_pivot import snapshot_pivot_levels
from signal_engine.paper.m5_htf import htf_pivot_early_engulf_setup, htf_pivot_setup, newest_pivot_reason
from signal_engine.paper.vacuum_senior_gate import vacuum_senior_allows_entry
from signal_engine.state import SymbolState
from signal_engine.paper.ma333_regime import ma333_regime_allows
from signal_engine.vacuum_lh import _meets_turnover, hour_range_pct

PYL_INTERVAL = config.PAPER_PYL_INTERVAL

PYL_MANDATORY_5 = (
    "turnover_ok",
    "pivot_left",
    "side_from_pivot",
    "senior_tf_trend",
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
    "senior_tf_trend": "Старший TF: LH↓ только шорт, HL↑ только лонг (2 pivot, mixed→3)",
}

PYL1_MANDATORY_5 = (
    "turnover_ok",
    "hour_range_ok",
    "pivot_left",
    "structure_ok",
    "side_from_pivot",
    "senior_tf_trend",
)

PYL1_CHECK_LABELS = {
    **PYL_CHECK_LABELS,
    "hour_range_ok": f"Размах цены за час ≥ {config.PAPER_PYL1_HOUR_RANGE_PCT:g}%",
    "structure_ok": "Не расширение; лонг: min выше prev, шорт: max ниже prev",
}

PYL333_MANDATORY_5 = PYL_MANDATORY_5 + ("ma333_regime",)

PYL333_CHECK_LABELS = {
    **PYL_CHECK_LABELS,
    "ma333_regime": (
        f"EMA60: |Δ| ≥ {config.PAPER_333_MA_SLOPE_MIN_PCT:g}% — тренд; "
        f"лонг EMA…+{config.PAPER_333_MA_BAND_PCT:g}% при EMA↑ или >{config.PAPER_333_MA_STRETCH_PCT:g}% ниже при EMA↓; "
        f"шорт зеркально; мёртвая зона {config.PAPER_333_MA_BAND_PCT:g}–{config.PAPER_333_MA_STRETCH_PCT:g}%"
    ),
}

PYL33315_MANDATORY = ("turnover_ok", "pivot_left", "side_from_pivot", "ma333_regime")

PYL33315_CHECK_LABELS = {
    **PYL_CHECK_LABELS,
    "ma333_regime": (
        f"EMA60 (15m): |Δ| ≥ {config.PAPER_333_MA_SLOPE_MIN_PCT:g}% — тренд; "
        f"полоса ±{config.PAPER_333_MA_BAND_PCT:g}% / stretch >{config.PAPER_333_MA_STRETCH_PCT:g}%"
    ),
}


def _last_two_prices(points: list[dict]) -> tuple[float, float] | None:
    if len(points) < 2:
        return None
    return float(points[-2]["price"]), float(points[-1]["price"])


def structure_bias_two_pivots(peaks: list[dict], troughs: list[dict]) -> str:
    """up | down | mixed — по двум последним pivot high и low на TF."""
    pp = _last_two_prices(peaks)
    tt = _last_two_prices(troughs)
    if pp is None or tt is None:
        return "mixed"
    p0, p1 = pp
    t0, t1 = tt
    if p1 > p0 and t1 > t0:
        return "up"
    if p1 < p0 and t1 < t0:
        return "down"
    return "mixed"


def pyl1_range_expanding(peaks: list[dict], troughs: list[dict]) -> bool:
    """Запрет входа: последний high выше prev и последний low ниже prev (диапазон расширяется)."""
    pp = _last_two_prices(peaks)
    tt = _last_two_prices(troughs)
    if pp is None or tt is None:
        return False
    return pp[1] > pp[0] and tt[1] < tt[0]


def pyl1_structure_allows_entry(side: str, peaks: list[dict], troughs: list[dict]) -> bool:
    if pyl1_range_expanding(peaks, troughs):
        return False
    if side == "long":
        tt = _last_two_prices(troughs)
        return tt is not None and tt[1] > tt[0]
    if side == "short":
        pp = _last_two_prices(peaks)
        return pp is not None and pp[1] < pp[0]
    return False


def _pyl1_structure_detail(side: str | None, peaks: list[dict], troughs: list[dict]) -> str:
    if not side:
        return "—"
    if pyl1_range_expanding(peaks, troughs):
        return "расширение: high↑ и low↓"
    if side == "long":
        tt = _last_two_prices(troughs)
        if tt is None:
            return "нет 2 pivot low"
        return f"min {tt[1]:g} vs {tt[0]:g}"
    pp = _last_two_prices(peaks)
    if pp is None:
        return "нет 2 pivot high"
    return f"max {pp[1]:g} vs {pp[0]:g}"


def mandatory_for_interval(interval: str) -> tuple[str, ...]:
    if interval in ("5", "15"):
        return PYL_MANDATORY_5
    return PYL_MANDATORY_15


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
    pivot_signal: dict | None = None,
) -> dict:
    del prev_snap
    snap = snapshot_pivot_levels(state, interval, now_ms)
    turnover_ok = _meets_turnover(state)
    mandatory = mandatory_for_interval(interval)
    reason = newest_pivot_reason(state, now_ms, interval) if turnover_ok else "no_bar"
    if pivot_signal is not None:
        signal = pivot_signal if turnover_ok else None
    else:
        signal = htf_pivot_setup(state, now_ms, interval) if turnover_ok else None
    side_ok = signal is not None and signal.get("side") in ("short", "long")
    ls = int(signal.get("left_strength") or 0) if signal else 0

    side = signal.get("side") if signal else None
    senior_ok, senior_detail = (
        vacuum_senior_allows_entry(state, now_ms, interval, str(side))
        if side_ok and side in ("short", "long")
        else (False, "—")
    )

    if interval in ("5", "15"):
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
            "senior_tf_trend": _check(
                senior_ok,
                senior_detail,
                PYL_CHECK_LABELS["senior_tf_trend"],
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
        if signal.get("entry_path"):
            metrics["entry_path"] = signal["entry_path"]
        if signal.get("engulf_detail"):
            metrics["engulf_detail"] = signal["engulf_detail"]
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


def evaluate_333(state: SymbolState, now_ms: int, prev_snap: dict | None = None) -> dict:
    pivot_signal = htf_pivot_setup(state, now_ms, PYL_INTERVAL)
    if pivot_signal is None:
        pivot_signal = htf_pivot_early_engulf_setup(state, now_ms, PYL_INTERVAL)
    base = evaluate_htf_pivot_entry(
        state,
        now_ms,
        prev_snap,
        PYL_INTERVAL,
        kind="333",
        variant=config.PAPER_333_VARIANT,
        pivot_signal=pivot_signal,
    )
    side = base.get("side") or (base.get("metrics") or {}).get("side")
    ma_ok, ma_detail, ma_meta = ma333_regime_allows(state, now_ms, side, PYL_INTERVAL)
    checks = dict(base.get("checks") or {})
    checks["ma333_regime"] = _check(ma_ok, ma_detail, PYL333_CHECK_LABELS["ma333_regime"])
    mandatory = PYL333_MANDATORY_5
    failed = [k for k in mandatory if not checks[k]["ok"]]
    passed = not failed
    out = dict(base)
    out["checks"] = checks
    out["failed"] = failed
    out["passed"] = passed
    out["passed_count"] = len(mandatory) - len(failed)
    out["score"] = 92.0 if passed else 25.0
    out["grade"] = grade_for(out["score"])
    out["variants"] = [config.PAPER_333_VARIANT] if passed else []
    out["side"] = side if passed else None
    metrics = dict(out.get("metrics") or {})
    metrics["ma333"] = ma_meta
    out["metrics"] = metrics
    return out


def evaluate_33315(state: SymbolState, now_ms: int, prev_snap: dict | None = None) -> dict:
    iv = config.PAPER_33315_INTERVAL
    base = evaluate_htf_pivot_entry(
        state,
        now_ms,
        prev_snap,
        iv,
        kind="33315",
        variant=config.PAPER_33315_VARIANT,
    )
    side = base.get("side") or (base.get("metrics") or {}).get("side")
    ma_ok, ma_detail, ma_meta = ma333_regime_allows(state, now_ms, side, iv)
    checks = dict(base.get("checks") or {})
    checks["ma333_regime"] = _check(ma_ok, ma_detail, PYL33315_CHECK_LABELS["ma333_regime"])
    mandatory = PYL33315_MANDATORY
    failed = [k for k in mandatory if not checks[k]["ok"]]
    passed = not failed
    out = dict(base)
    out["checks"] = checks
    out["failed"] = failed
    out["passed"] = passed
    out["passed_count"] = len(mandatory) - len(failed)
    out["score"] = 92.0 if passed else 25.0
    out["grade"] = grade_for(out["score"])
    out["variants"] = [config.PAPER_33315_VARIANT] if passed else []
    out["side"] = side if passed else None
    metrics = dict(out.get("metrics") or {})
    metrics["ma333"] = ma_meta
    out["metrics"] = metrics
    return out


def evaluate_pyl1(state: SymbolState, now_ms: int, prev_snap: dict | None = None) -> dict:
    del prev_snap
    base = evaluate_htf_pivot_entry(
        state,
        now_ms,
        None,
        PYL_INTERVAL,
        kind="pyl1",
        variant=config.PAPER_PYL1_VARIANT,
    )
    snap = snapshot_pivot_levels(state, PYL_INTERVAL, now_ms)
    peaks = list((snap or {}).get("peaks") or base.get("metrics", {}).get("peaks") or [])
    troughs = list((snap or {}).get("troughs") or base.get("metrics", {}).get("troughs") or [])
    side = base.get("side")
    hr = hour_range_pct(state, now_ms)
    hour_ok = hr is not None and hr + 1e-12 >= config.PAPER_PYL1_HOUR_RANGE_PCT
    bias = structure_bias_two_pivots(peaks, troughs)
    struct_ok = bool(side) and pyl1_structure_allows_entry(str(side), peaks, troughs)

    checks = dict(base.get("checks") or {})
    checks["hour_range_ok"] = _check(
        hour_ok,
        f"{hr:.2f}%" if hr is not None else "нет данных",
        f"≥ {config.PAPER_PYL1_HOUR_RANGE_PCT:g}% за час",
    )
    checks["structure_ok"] = _check(
        struct_ok,
        _pyl1_structure_detail(side, peaks, troughs),
        PYL1_CHECK_LABELS["structure_ok"],
    )

    mandatory = PYL1_MANDATORY_5
    failed = [k for k in mandatory if not checks[k]["ok"]]
    passed = not failed
    out = dict(base)
    out["checks"] = checks
    out["failed"] = failed
    out["passed"] = passed
    out["passed_count"] = len(mandatory) - len(failed)
    out["score"] = 92.0 if passed else 25.0
    out["grade"] = grade_for(out["score"])
    out["variants"] = [config.PAPER_PYL1_VARIANT] if passed else []
    out["side"] = side if passed else None
    metrics = dict(out.get("metrics") or {})
    metrics["hour_range_pct"] = round(float(hr), 2) if hr is not None else None
    metrics["structure_bias"] = bias
    metrics["peaks"] = peaks[-3:]
    metrics["troughs"] = troughs[-3:]
    out["metrics"] = metrics
    return out
