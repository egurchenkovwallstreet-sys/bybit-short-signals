"""TZ-pivot L15–L30 (left_strength), 2 справа.

5m (pyl/vps5): LH/HL без 15m/30m; в окне 3-й свечи — кандидат с max left_strength.
15m (vps15): LH/HL L15–L30; вход/выход 10 с после 1-й закрытой 15m справа, затем re-enter.
"""

from __future__ import annotations

import config
from signal_engine.paper.lh_scan_pivot import (
    pivot_has_one_right_bar,
    pivot_has_two_right_bars,
    snapshot_pivot_levels,
)
from signal_engine.paper.pivot_clock import (
    confirm_bar_close_ms,
    entry_on_third_bar,
    just_confirmed,
    second_bar_close_ms,
    vps15_entry_confirmed,
    vps15_pivot_confirmed,
)
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars, pivot_highs_floating_left, pivot_lows_floating_left
from signal_engine.vacuum_lh import _meets_turnover

M5 = 300_000
M15 = 900_000
M30 = 1_800_000
M60 = 3_600_000
M240 = 14_400_000

_BAR_STEP = {"5": M5, "15": M15}
# (floor step, bars in current HTF bucket, prior floor step, bars in prior HTF bucket)
_HTF_BUCKETS: dict[str, tuple[int, int, int, int]] = {
    "5": (M15, 3, M30, 6),
    "15": (M60, 4, M240, 16),
}


def _floor(ts: int, step: int) -> int:
    return int(ts) - (int(ts) % step)


def _index(bars: list[Bar]) -> dict[int, Bar]:
    return {int(b.timestamp): b for b in bars}


def _span(index: dict[int, Bar], start: int, count: int, step: int) -> list[Bar] | None:
    out: list[Bar] = []
    for i in range(count):
        bar = index.get(start + i * step)
        if bar is None:
            return None
        out.append(bar)
    return out


def qualify_htf_pivot(index: dict[int, Bar], pivot_ts: int, side: str, interval: str = "5") -> str:
    """'ok' — TZ-pivot прошёл фильтр старшего ТФ для interval (5 или 15)."""
    bar = index.get(int(pivot_ts))
    step = _BAR_STEP.get(interval)
    bucket = _HTF_BUCKETS.get(interval)
    if bar is None or side not in ("short", "long") or step is None or bucket is None:
        return "no_bar"
    cur_floor, cur_n, prior_floor, prior_n = bucket
    open_cur = _floor(pivot_ts, cur_floor)
    cur = _span(index, open_cur, cur_n, step)
    prev = _span(index, open_cur - cur_floor, cur_n, step)
    if cur is None or prev is None:
        return "missing_15m" if interval == "5" else "missing_1h"
    if side == "short":
        price = float(bar.high)
        if price < max(float(b.high) for b in cur):
            return "not_15m_extreme" if interval == "5" else "not_1h_extreme"
        holders = [b for b in cur if float(b.high) == price]
        if int(holders[-1].timestamp) != int(pivot_ts):
            return "not_15m_extreme" if interval == "5" else "not_1h_extreme"
        if price >= max(float(b.high) for b in prev):
            return "not_weaker_15m" if interval == "5" else "not_weaker_1h"
        prior = _span(index, _floor(pivot_ts, prior_floor) - prior_floor, prior_n, step)
        if prior is None:
            return "missing_30m" if interval == "5" else "missing_4h"
        if price > max(float(b.high) for b in prior):
            return "break_30m" if interval == "5" else "break_4h"
        for n in (1, 2):
            right = index.get(int(pivot_ts) + n * step)
            if right is None or float(right.high) >= price:
                return "right_broken"
    else:
        price = float(bar.low)
        if price > min(float(b.low) for b in cur):
            return "not_15m_extreme" if interval == "5" else "not_1h_extreme"
        holders = [b for b in cur if float(b.low) == price]
        if int(holders[-1].timestamp) != int(pivot_ts):
            return "not_15m_extreme" if interval == "5" else "not_1h_extreme"
        if price <= min(float(b.low) for b in prev):
            return "not_weaker_15m" if interval == "5" else "not_weaker_1h"
        prior = _span(index, _floor(pivot_ts, prior_floor) - prior_floor, prior_n, step)
        if prior is None:
            return "missing_30m" if interval == "5" else "missing_4h"
        if price < min(float(b.low) for b in prior):
            return "break_30m" if interval == "5" else "break_4h"
        for n in (1, 2):
            right = index.get(int(pivot_ts) + n * step)
            if right is None or float(right.low) <= price:
                return "right_broken"
    return "ok"


def qualify_m5_pivot(index: dict[int, Bar], pivot_ts: int, side: str) -> str:
    return qualify_htf_pivot(index, pivot_ts, side, "5")


def _pack(bar: Bar, side: str, left_strength: int | None = None) -> dict:
    price = float(bar.high) if side == "short" else float(bar.low)
    ts = int(bar.timestamp)
    out = {
        "side": side,
        "signal_key": f"{side}:{ts}:{price}",
        "pivot_time_ms": ts,
        "pivot_price": price,
        "pivot_kind": "peak" if side == "short" else "trough",
        "pivot_high": float(bar.high),
        "pivot_low": float(bar.low),
    }
    if left_strength is not None:
        out["left_strength"] = int(left_strength)
    return out


def _pivot_left_strength(p: dict) -> int | None:
    ls = int(p.get("left_strength") or 0)
    lo = config.VACUUM_LH_PIVOT_LEFT
    hi = config.VACUUM_LH_PIVOT_LEFT_MAX
    if lo <= ls <= hi:
        return ls
    return None


def _tz_pivot_times_ms(snap: dict) -> list[int]:
    times: set[int] = set()
    for p in snap.get("peaks") or []:
        t = int(p.get("time_ms") or 0)
        if t > 0:
            times.add(t)
    for p in snap.get("troughs") or []:
        t = int(p.get("time_ms") or 0)
        if t > 0:
            times.add(t)
    return sorted(times, reverse=True)


def _pivot_in_entry_window(ts: int, now_ms: int, interval: str, step: int) -> bool:
    del step
    if interval == "5":
        return entry_on_third_bar(ts, now_ms, "5")
    if interval == "15":
        return vps15_entry_confirmed(ts, now_ms)
    return int(now_ms) >= second_bar_close_ms(ts, interval)


def _setup_vps15_entry(state: SymbolState, now_ms: int) -> dict | None:
    """Пылесос 15: pivot L15–L30, 1 закрытая 15m справа, окно 10 с."""
    step = M15
    if not _meets_turnover(state):
        return None
    bars = closed_bars(state.bars_htf.get("15") or [], "15", now_ms)
    if len(bars) < 12:
        return None
    index = _index(bars)
    left = config.VACUUM_LH_PIVOT_LEFT
    left_max = config.VACUUM_LH_PIVOT_LEFT_MAX
    right = config.PAPER_VPS15_ENTRY_PIVOT_RIGHT
    candidates: list[tuple[int, int, str]] = []
    for point in pivot_highs_floating_left(bars, left, left_max, right):
        ts = int(point["time"])
        ls = _pivot_left_strength(point)
        if ls is None or not vps15_entry_confirmed(ts, now_ms):
            continue
        if not pivot_has_one_right_bar(index, ts, step):
            continue
        candidates.append((ls, ts, "short"))
    for point in pivot_lows_floating_left(bars, left, left_max, right):
        ts = int(point["time"])
        ls = _pivot_left_strength(point)
        if ls is None or not vps15_entry_confirmed(ts, now_ms):
            continue
        if not pivot_has_one_right_bar(index, ts, step):
            continue
        candidates.append((ls, ts, "long"))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    ls, ts, side = candidates[0]
    bar = index.get(ts)
    if bar is None:
        return None
    return _pack(bar, side, ls)


def _setup_from_tz_pivots(state: SymbolState, now_ms: int, interval: str) -> dict | None:
    """Pivot L15–L30; 5m — 2 справа; 15m vps15 — 1 справа для входа."""
    step = _BAR_STEP.get(interval)
    if step is None:
        return None
    if interval == "15":
        return _setup_vps15_entry(state, now_ms)
    snap = snapshot_pivot_levels(state, interval, now_ms)
    if not snap:
        return None
    bars = closed_bars(state.bars_htf.get(interval) or [], interval, now_ms)
    if len(bars) < 12:
        return None
    index = _index(bars)
    candidates: list[tuple[int, int, str]] = []
    for p in snap.get("peaks") or []:
        ts = int(p["time_ms"])
        ls = _pivot_left_strength(p)
        if ls is None or not _pivot_in_entry_window(ts, now_ms, interval, step):
            continue
        if not pivot_has_two_right_bars(index, ts, step):
            continue
        if interval in ("5", "15"):
            candidates.append((ls, ts, "short"))
        elif qualify_htf_pivot(index, ts, "short", interval) == "ok":
            candidates.append((ls, ts, "short"))
    for p in snap.get("troughs") or []:
        ts = int(p["time_ms"])
        ls = _pivot_left_strength(p)
        if ls is None or not _pivot_in_entry_window(ts, now_ms, interval, step):
            continue
        if not pivot_has_two_right_bars(index, ts, step):
            continue
        if interval in ("5", "15"):
            candidates.append((ls, ts, "long"))
        elif qualify_htf_pivot(index, ts, "long", interval) == "ok":
            candidates.append((ls, ts, "long"))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    ls, ts, side = candidates[0]
    bar = index.get(ts)
    if bar is None:
        return None
    return _pack(bar, side, ls)


def newest_pivot_reason(state: SymbolState, now_ms: int, interval: str = "5") -> str:
    """Причина по TZ-pivot в окне входа (L15–L30, без HTF на 5m/15m)."""
    if interval in ("5", "15"):
        return "ok" if htf_pivot_setup(state, now_ms, interval) else "no_bar"
    step = _BAR_STEP.get(interval)
    if step is None:
        return "no_bar"
    snap = snapshot_pivot_levels(state, interval, now_ms)
    if not snap:
        return "no_bar"
    bars = closed_bars(state.bars_htf.get(interval) or [], interval, now_ms)
    if len(bars) < 12:
        return "no_bar"
    index = _index(bars)
    fallback = "no_bar"
    not_ext = "not_1h_extreme"
    for ts in _tz_pivot_times_ms(snap):
        if not _pivot_in_entry_window(ts, now_ms, interval, step):
            continue
        if index.get(ts + step) is None or index.get(ts + 2 * step) is None:
            continue
        reasons = [qualify_htf_pivot(index, ts, side, interval) for side in ("short", "long")]
        if "ok" in reasons:
            return "ok"
        for reason in reasons:
            if reason not in (not_ext,):
                return reason
        fallback = not_ext
    return fallback


def htf_pivot_setup(state: SymbolState, now_ms: int, interval: str) -> dict | None:
    """TZ-pivot в окне входа; 5m/15m — max L15–L30 без HTF."""
    if not _meets_turnover(state):
        return None
    return _setup_from_tz_pivots(state, now_ms, interval)


def m5_htf_setup(state: SymbolState, now_ms: int) -> dict | None:
    return htf_pivot_setup(state, now_ms, "5")


def htf_second_bar_pending(state: SymbolState, now_ms: int) -> bool:
    """Первая свеча справа закрыта, вторая ещё нет, 15м пока слабее предыдущей."""
    if not _meets_turnover(state):
        return False
    bars = closed_bars(state.bars_htf.get("5") or [], "5", now_ms)
    index = _index(bars)
    anchor = int(now_ms) - 2 * M5
    pivot_ts = _floor(anchor, M5)
    if not (pivot_ts + 2 * M5 <= int(now_ms) < pivot_ts + 3 * M5):
        return False
    bar = index.get(pivot_ts)
    right = index.get(pivot_ts + M5)
    if bar is None or right is None:
        return False
    open15 = _floor(pivot_ts, M15)
    prev = _span(index, open15 - M15, 3, M5)
    if prev is None:
        return False
    cur: list[Bar] = []
    for i in range(3):
        item = index.get(open15 + i * M5)
        if item is not None and int(item.timestamp) + M5 <= int(now_ms):
            cur.append(item)
    if not cur:
        return False
    high = float(bar.high)
    if float(right.high) < high and high == max(float(b.high) for b in cur):
        holders = [b for b in cur if float(b.high) == high]
        if int(holders[-1].timestamp) == pivot_ts and high < max(float(b.high) for b in prev):
            return True
    low = float(bar.low)
    if float(right.low) > low and low == min(float(b.low) for b in cur):
        holders = [b for b in cur if float(b.low) == low]
        if int(holders[-1].timestamp) == pivot_ts and low > min(float(b.low) for b in prev):
            return True
    return False


def symbols_waiting_htf_second_bar(states: dict[str, SymbolState], now_ms: int) -> set[str]:
    return {symbol for symbol, state in states.items() if htf_second_bar_pending(state, now_ms)}


def opposite_pivot_exit_signal(
    state: SymbolState,
    now_ms: int,
    open_side: str,
    opened_at_ms: int,
    interval: str = "5",
) -> dict | None:
    """БАБЛОСОС: выход по противоп. TZ-pivot (как на графике LH/HL), после 2-й свечи справа."""
    if interval == "5":
        hit = opposite_anchor_pivot_exit(state, now_ms, open_side, opened_at_ms, interval)
    else:
        hit = opposite_appeared(state, now_ms, open_side, opened_at_ms, interval)
    if not hit:
        return None
    if int(now_ms) < second_bar_close_ms(int(hit["pivot_time_ms"]), interval):
        return None
    return hit


def _opposite_vps15_one_bar_exit(
    state: SymbolState,
    now_ms: int,
    open_side: str,
    opened_at_ms: int,
) -> dict | None:
    """Противоп. pivot L15–L30, 1 закрытая 15m справа, окно 10 с (как вход)."""
    if open_side not in ("long", "short"):
        return None
    want = "short" if open_side == "long" else "long"
    bars = closed_bars(state.bars_htf.get("15") or [], "15", now_ms)
    if len(bars) < 12:
        return None
    index = _index(bars)
    left = config.VACUUM_LH_PIVOT_LEFT
    left_max = config.VACUUM_LH_PIVOT_LEFT_MAX
    right = config.PAPER_VPS15_ENTRY_PIVOT_RIGHT
    opened = int(opened_at_ms)
    points = (
        pivot_highs_floating_left(bars, left, left_max, right)
        if want == "short"
        else pivot_lows_floating_left(bars, left, left_max, right)
    )
    hit: dict | None = None
    for point in points:
        ts = int(point["time"])
        ls = _pivot_left_strength(point)
        if ls is None or not pivot_has_one_right_bar(index, ts, M15):
            continue
        confirmed_at = confirm_bar_close_ms(ts, "15", right)
        if confirmed_at <= opened or confirmed_at > int(now_ms):
            continue
        if not vps15_pivot_confirmed(ts, now_ms):
            continue
        if hit is None or ts > int(hit["pivot_time_ms"]):
            bar = index.get(ts)
            if bar is None:
                continue
            hit = _pack(bar, want, ls)
    return hit


def opposite_anchor_pivot_exit(
    state: SymbolState,
    now_ms: int,
    open_side: str,
    opened_at_ms: int,
    interval: str,
) -> dict | None:
    """Противоп. TZ-pivot: vps15 — 1×15m справа и 10 с; 5m — 2×5m (snap LH/HL)."""
    if open_side not in ("long", "short"):
        return None
    if interval == "15":
        return _opposite_vps15_one_bar_exit(state, now_ms, open_side, opened_at_ms)
    step = _BAR_STEP.get(interval)
    if step is None:
        return None
    want = "short" if open_side == "long" else "long"
    snap = snapshot_pivot_levels(state, interval, now_ms)
    if not snap:
        return None
    bars = closed_bars(state.bars_htf.get(interval) or [], interval, now_ms)
    index = _index(bars)
    points = list(snap.get("peaks") if want == "short" else snap.get("troughs") or [])
    opened = int(opened_at_ms)
    hit: dict | None = None
    for p in points:
        ts = int(p["time_ms"])
        ls = _pivot_left_strength(p)
        if ls is None:
            continue
        if not pivot_has_two_right_bars(index, ts, step):
            continue
        confirmed_at = second_bar_close_ms(ts, interval)
        if confirmed_at <= opened or confirmed_at > int(now_ms):
            continue
        if hit is None or ts > int(hit["pivot_time_ms"]):
            bar = index.get(ts)
            if bar is None:
                continue
            hit = _pack(bar, want, ls)
    return hit


def opposite_appeared(
    state: SymbolState,
    now_ms: int,
    open_side: str,
    opened_at_ms: int,
    interval: str = "5",
) -> dict | None:
    """Противоположный L15–L30, вторая свеча которого закрылась уже после входа."""
    if open_side not in ("long", "short"):
        return None
    want = "short" if open_side == "long" else "long"
    bars = closed_bars(state.bars_htf.get(interval) or [], interval, now_ms)
    left = config.VACUUM_LH_PIVOT_LEFT
    left_max = config.VACUUM_LH_PIVOT_LEFT_MAX
    right = config.VACUUM_LH_PIVOT_RIGHT
    points = (
        pivot_highs_floating_left(bars, left, left_max, right)
        if want == "short"
        else pivot_lows_floating_left(bars, left, left_max, right)
    )
    opened = int(opened_at_ms)
    hit: dict | None = None
    for point in points:
        ts = int(point["time"])
        confirmed_at = second_bar_close_ms(ts, interval)
        if confirmed_at > int(now_ms) or confirmed_at <= opened:
            continue
        if hit is None or ts > int(hit["pivot_time_ms"]):
            hit = {
                "side": want,
                "pivot_time_ms": ts,
                "pivot_price": float(point["price"]),
                "pivot_kind": "peak" if want == "short" else "trough",
            }
    return hit
