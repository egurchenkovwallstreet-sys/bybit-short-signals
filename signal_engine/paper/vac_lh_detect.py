"""Пылесос (paper): 15m новый pivot — шорт ниже двух прошлых максимумов, лонг выше двух минимумов."""

from __future__ import annotations

from signal_engine.paper.detect import _check, grade_for
from signal_engine.state import SymbolState
from signal_engine.vacuum_lh_live import snapshot_15m_levels

VPS_MANDATORY = (
    "turnover_ok",
    "new_pivot",
    "structure_vs_two_prev",
)

VPS_CHECK_LABELS = {
    "turnover_ok": "Оборот 24ч ≥ порога сканера LH",
    "new_pivot": "Новый подтверждённый pivot на 15m",
    "structure_vs_two_prev": "Шорт: max ниже двух прошлых max; лонг: min выше двух прошлых min",
}


def _keys(points: list[dict]) -> frozenset[tuple[int, float]]:
    out: set[tuple[int, float]] = set()
    for p in points:
        t = int(p.get("time_ms") or p.get("time") or 0)
        out.add((t, round(float(p["price"]), 8)))
    return frozenset(out)


def _ordered(points: list[dict]) -> list[dict]:
    return sorted(points, key=lambda p: int(p["time_ms"]))


def side_for_new_peak(peaks: list[dict], new_key: tuple[int, float]) -> str | None:
    ordered = _ordered(peaks)
    idx = next(
        (
            i
            for i, p in enumerate(ordered)
            if (int(p["time_ms"]), round(float(p["price"]), 8)) == new_key
        ),
        -1,
    )
    if idx < 2:
        return None
    p0, p1, p2 = float(ordered[idx - 2]["price"]), float(ordered[idx - 1]["price"]), float(ordered[idx]["price"])
    if p2 < p1 and p2 < p0:
        return "short"
    return None


def side_for_new_trough(troughs: list[dict], new_key: tuple[int, float]) -> str | None:
    ordered = _ordered(troughs)
    idx = next(
        (
            i
            for i, p in enumerate(ordered)
            if (int(p["time_ms"]), round(float(p["price"]), 8)) == new_key
        ),
        -1,
    )
    if idx < 2:
        return None
    p0, p1, p2 = float(ordered[idx - 2]["price"]), float(ordered[idx - 1]["price"]), float(ordered[idx]["price"])
    if p2 > p1 and p2 > p0:
        return "long"
    return None


def detect_entry_signal(prev: dict | None, cur: dict) -> dict | None:
    if not prev or not cur:
        return None
    new_peaks = _keys(cur.get("peaks") or []) - _keys(prev.get("peaks") or [])
    new_troughs = _keys(cur.get("troughs") or []) - _keys(prev.get("troughs") or [])
    if not new_peaks and not new_troughs:
        return None
    events: list[tuple[int, str, tuple[int, float], float]] = []
    for key in new_peaks:
        side = side_for_new_peak(cur.get("peaks") or [], key)
        if side:
            events.append((key[0], side, key, float(key[1])))
    for key in new_troughs:
        side = side_for_new_trough(cur.get("troughs") or [], key)
        if side:
            events.append((key[0], side, key, float(key[1])))
    if not events:
        return None
    events.sort(key=lambda x: x[0])
    t_ms, side, key, price = events[-1]
    return {
        "side": side,
        "signal_key": f"{side}:{key[0]}:{key[1]}",
        "pivot_time_ms": t_ms,
        "pivot_price": price,
        "pivot_kind": "peak" if side == "short" else "trough",
    }


def evaluate_vps(state: SymbolState, now_ms: int, prev_snap: dict | None) -> dict:
    snap = snapshot_15m_levels(state, now_ms)
    signal = detect_entry_signal(prev_snap, snap) if snap else None
    turnover_ok = snap is not None
    new_pivot = signal is not None
    structure_ok = new_pivot

    checks = {
        "turnover_ok": _check(turnover_ok, turnover_ok, "да", "нет данных / оборот"),
        "new_pivot": _check(new_pivot, new_pivot, "новый pivot", "нет"),
        "structure_vs_two_prev": _check(
            structure_ok,
            structure_ok,
            signal.get("side") if signal else "—",
            "не ниже/выше двух прошлых",
        ),
    }
    failed = [k for k in VPS_MANDATORY if not checks[k]["ok"]]
    passed = len(VPS_MANDATORY) - len(failed)
    metrics: dict = {
        "kind": "vps",
        "pump": {"kind": "vps", "side": signal.get("side") if signal else None},
    }
    if signal:
        metrics.update(
            {
                "signal_key": signal["signal_key"],
                "pivot_time_ms": signal["pivot_time_ms"],
                "pivot_price": signal["pivot_price"],
                "pivot_kind": signal["pivot_kind"],
                "side": signal["side"],
            }
        )
    if snap:
        metrics["peaks"] = list(snap.get("peaks") or [])
        metrics["troughs"] = list(snap.get("troughs") or [])

    return {
        "checks": checks,
        "failed": failed,
        "passed_count": passed,
        "passed": passed == len(VPS_MANDATORY),
        "grade": grade_for(passed, len(VPS_MANDATORY)),
        "score": float(passed),
        "metrics": metrics,
    }
