"""Paper Пылесос 15 / 5: новый pivot-high → шорт, pivot-low → лонг; окно входа — 3 свечи после подтверждения."""

from __future__ import annotations

import config
from signal_engine.paper.detect import _check, grade_for
from signal_engine.state import SymbolState
from signal_engine.vacuum_lh import (
    _bars_for_interval,
    _meets_turnover,
    _min_bars,
    all_anchor_peaks,
    all_anchor_troughs,
)

_INTERVAL_MS = {
    "5": 300_000,
    "15": 900_000,
    "30": 1_800_000,
    "60": 3_600_000,
    "240": 14_400_000,
}

VPS_MANDATORY = (
    "turnover_ok",
    "new_pivot",
    "structure_vs_prev",
    "entry_window",
)

VPS_CHECK_LABELS = {
    "turnover_ok": "Оборот 24ч ≥ порога сканера LH",
    "new_pivot": "Новый подтверждённый pivot (max или min)",
    "structure_vs_prev": "Шорт — уровень сверху (max); лонг — уровень снизу (min)",
    "entry_window": "Не позже 3-й свечи после подтверждения pivot",
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


def entry_open_until_ms(pivot_time_ms: int, interval: str) -> int:
    pr = int(config.VACUUM_LH_PIVOT_RIGHT)
    n = int(config.PAPER_VPS_ENTRY_CANDLES)
    step = _INTERVAL_MS.get(interval, 300_000)
    signal_start = int(pivot_time_ms) + pr * step
    return signal_start + n * step


def pivot_in_entry_window(pivot_time_ms: int, interval: str, now_ms: int) -> bool:
    return int(now_ms) < entry_open_until_ms(pivot_time_ms, interval)


def _pack_signal(t_ms: int, side: str, key: tuple[int, float], price: float, interval: str) -> dict:
    return {
        "side": side,
        "signal_key": f"{side}:{key[0]}:{key[1]}",
        "pivot_time_ms": t_ms,
        "pivot_price": price,
        "pivot_kind": "peak" if side == "short" else "trough",
        "entry_until_ms": entry_open_until_ms(t_ms, interval),
    }


def _events_from_points(
    peaks: list[dict], troughs: list[dict]
) -> list[tuple[int, str, tuple[int, float], float]]:
    events: list[tuple[int, str, tuple[int, float], float]] = []
    for p in peaks:
        key = (int(p["time_ms"]), round(float(p["price"]), 8))
        events.append((key[0], "short", key, float(p["price"])))
    for p in troughs:
        key = (int(p["time_ms"]), round(float(p["price"]), 8))
        events.append((key[0], "long", key, float(p["price"])))
    return events


def _pick_latest_in_window(cur: dict, interval: str, now_ms: int) -> dict | None:
    """Последний pivot по времени среди max/min, если окно входа ещё открыто."""
    events = _events_from_points(cur.get("peaks") or [], cur.get("troughs") or [])
    in_window = [e for e in events if pivot_in_entry_window(e[0], interval, now_ms)]
    if not in_window:
        return None
    in_window.sort(key=lambda x: x[0])
    t_ms, side, key, price = in_window[-1]
    return _pack_signal(t_ms, side, key, price, interval)


def _signal_from_diff(prev: dict, cur: dict, interval: str, now_ms: int) -> dict | None:
    new_peaks = _keys(cur.get("peaks") or []) - _keys(prev.get("peaks") or [])
    new_troughs = _keys(cur.get("troughs") or []) - _keys(prev.get("troughs") or [])
    if not new_peaks and not new_troughs:
        return None
    events: list[tuple[int, str, tuple[int, float], float]] = []
    for key in new_peaks:
        events.append((key[0], "short", key, float(key[1])))
    for key in new_troughs:
        events.append((key[0], "long", key, float(key[1])))
    events = [e for e in events if pivot_in_entry_window(e[0], interval, now_ms)]
    if not events:
        return None
    events.sort(key=lambda x: x[0])
    t_ms, side, key, price = events[-1]
    return _pack_signal(t_ms, side, key, price, interval)


def latest_qualifying_signal(cur: dict, interval: str, now_ms: int) -> dict | None:
    return _pick_latest_in_window(cur, interval, now_ms)


def detect_entry_signal(prev: dict | None, cur: dict, interval: str, now_ms: int) -> dict | None:
    if not cur:
        return None
    prev_norm = prev or {"peaks": [], "troughs": []}
    sig = _signal_from_diff(prev_norm, cur, interval, now_ms)
    if sig:
        return sig
    return _pick_latest_in_window(cur, interval, now_ms)


def evaluate_vps(
    state: SymbolState, now_ms: int, prev_snap: dict | None, interval: str, *, kind: str
) -> dict:
    snap = snapshot_pivot_levels(state, interval, now_ms)
    signal = detect_entry_signal(prev_snap, snap, interval, now_ms) if snap else None
    turnover_ok = snap is not None
    new_pivot = signal is not None
    structure_ok = new_pivot
    window_ok = (
        signal is not None
        and pivot_in_entry_window(int(signal["pivot_time_ms"]), interval, now_ms)
    )

    checks = {
        "turnover_ok": _check(turnover_ok, turnover_ok, "да", "нет данных / оборот"),
        "new_pivot": _check(new_pivot, new_pivot, "новый pivot", "нет"),
        "structure_vs_prev": _check(
            structure_ok,
            structure_ok,
            signal.get("side") if signal else "—",
            "ждём новый max/min",
        ),
        "entry_window": _check(
            window_ok,
            window_ok,
            "в окне входа",
            "окно закрыто (3 свечи после pivot)",
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
                "entry_until_ms": signal.get("entry_until_ms"),
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
