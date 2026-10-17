"""Paper Пылесос 15 / 5: новый pivot — шорт если max ниже прошлого max, лонг если min выше прошлого min."""

from __future__ import annotations

from signal_engine.paper.detect import _check, grade_for
from signal_engine.state import SymbolState
from signal_engine.vacuum_lh import (
    _bars_for_interval,
    _meets_turnover,
    _min_bars,
    all_anchor_peaks,
    all_anchor_troughs,
)

VPS_MANDATORY = (
    "turnover_ok",
    "new_pivot",
    "structure_vs_prev",
)

VPS_CHECK_LABELS = {
    "turnover_ok": "Оборот 24ч ≥ порога сканера LH",
    "new_pivot": "Новый подтверждённый pivot",
    "structure_vs_prev": "Шорт: новый max ниже предыдущего; лонг: новый min выше предыдущего",
}


def snapshot_pivot_levels(state: SymbolState, interval: str, now_ms: int) -> dict | None:
    if not _meets_turnover(state):
        return None
    bars = _bars_for_interval(state, interval)
    if len(bars) < _min_bars(interval):
        return None
    peaks = all_anchor_peaks(bars, interval, now_ms)
    troughs = all_anchor_troughs(bars, interval, now_ms)
    return {
        "interval": interval,
        "peaks": peaks,
        "troughs": troughs,
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
    if idx < 1:
        return None
    if float(ordered[idx]["price"]) < float(ordered[idx - 1]["price"]):
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
    if idx < 1:
        return None
    if float(ordered[idx]["price"]) > float(ordered[idx - 1]["price"]):
        return "long"
    return None


def _pack_signal(t_ms: int, side: str, key: tuple[int, float], price: float) -> dict:
    return {
        "side": side,
        "signal_key": f"{side}:{key[0]}:{key[1]}",
        "pivot_time_ms": t_ms,
        "pivot_price": price,
        "pivot_kind": "peak" if side == "short" else "trough",
    }


def _signal_from_diff(prev: dict, cur: dict) -> dict | None:
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
    return _pack_signal(t_ms, side, key, price)


def latest_qualifying_signal(cur: dict) -> dict | None:
    """Последний pivot на TF: шорт/лонг vs предыдущий (если diff пропустили — рестарт, первый тик)."""
    events: list[tuple[int, str, tuple[int, float], float]] = []
    peaks = _ordered(cur.get("peaks") or [])
    if len(peaks) >= 2:
        prev_p, last_p = peaks[-2], peaks[-1]
        if float(last_p["price"]) < float(prev_p["price"]):
            key = (int(last_p["time_ms"]), round(float(last_p["price"]), 8))
            events.append((key[0], "short", key, float(last_p["price"])))
    troughs = _ordered(cur.get("troughs") or [])
    if len(troughs) >= 2:
        prev_t, last_t = troughs[-2], troughs[-1]
        if float(last_t["price"]) > float(prev_t["price"]):
            key = (int(last_t["time_ms"]), round(float(last_t["price"]), 8))
            events.append((key[0], "long", key, float(last_t["price"])))
    if not events:
        return None
    events.sort(key=lambda x: x[0])
    t_ms, side, key, price = events[-1]
    return _pack_signal(t_ms, side, key, price)


def detect_entry_signal(prev: dict | None, cur: dict) -> dict | None:
    if not cur:
        return None
    prev_norm = prev or {"peaks": [], "troughs": []}
    sig = _signal_from_diff(prev_norm, cur)
    if sig:
        return sig
    return latest_qualifying_signal(cur)


def evaluate_vps(
    state: SymbolState, now_ms: int, prev_snap: dict | None, interval: str, *, kind: str
) -> dict:
    snap = snapshot_pivot_levels(state, interval, now_ms)
    signal = detect_entry_signal(prev_snap, snap) if snap else None
    turnover_ok = snap is not None
    new_pivot = signal is not None
    structure_ok = new_pivot

    checks = {
        "turnover_ok": _check(turnover_ok, turnover_ok, "да", "нет данных / оборот"),
        "new_pivot": _check(new_pivot, new_pivot, "новый pivot", "нет"),
        "structure_vs_prev": _check(
            structure_ok,
            structure_ok,
            signal.get("side") if signal else "—",
            "нет LH/HL к прошлому",
        ),
    }
    failed = [k for k in VPS_MANDATORY if not checks[k]["ok"]]
    passed = len(VPS_MANDATORY) - len(failed)
    metrics: dict = {
        "kind": kind,
        "interval": interval,
        "pump": {"kind": kind, "side": signal.get("side") if signal else None, "trigger": interval},
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
