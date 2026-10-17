"""БАБЛОСОС / Пылесос 5: вход только от TZ-pivot на 5m (L15–L30, 2 справа, как LH/HL на графике).

Поверх pivot — фильтр 15m/30m (qualify_m5_pivot): экстремум своей 15m, слабее предыдущей 15m,
без пробоя предыдущей 30m, две 5m справа не обновляют. Вход — 10 секунд после второй справа.
"""

from __future__ import annotations

import config
from signal_engine.paper.lh_scan_pivot import snapshot_pivot_levels
from signal_engine.paper.pivot_clock import second_bar_close_ms
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars, pivot_highs_floating_left, pivot_lows_floating_left
from signal_engine.vacuum_lh import _meets_turnover

M5 = 300_000
M15 = 900_000
M30 = 1_800_000


def _floor(ts: int, step: int) -> int:
    return int(ts) - (int(ts) % step)


def _index(bars: list[Bar]) -> dict[int, Bar]:
    return {int(b.timestamp): b for b in bars}


def _span(index: dict[int, Bar], start: int, count: int) -> list[Bar] | None:
    out: list[Bar] = []
    for i in range(count):
        bar = index.get(start + i * M5)
        if bar is None:
            return None
        out.append(bar)
    return out


def qualify_m5_pivot(index: dict[int, Bar], pivot_ts: int, side: str) -> str:
    """Почему свеча годится или нет. 'ok' — можно входить на закрытии второй справа."""
    bar = index.get(int(pivot_ts))
    if bar is None or side not in ("short", "long"):
        return "no_bar"
    open15 = _floor(pivot_ts, M15)
    cur = _span(index, open15, 3)
    prev = _span(index, open15 - M15, 3)
    if cur is None or prev is None:
        return "missing_15m"
    if side == "short":
        price = float(bar.high)
        if price < max(float(b.high) for b in cur):
            return "not_15m_extreme"
        holders = [b for b in cur if float(b.high) == price]
        if int(holders[-1].timestamp) != int(pivot_ts):
            return "not_15m_extreme"
        if price >= max(float(b.high) for b in prev):
            return "not_weaker_15m"
        prior = _span(index, _floor(pivot_ts, M30) - M30, 6)
        if prior is None:
            return "missing_30m"
        if price > max(float(b.high) for b in prior):
            return "break_30m"
        for step in (1, 2):
            right = index.get(int(pivot_ts) + step * M5)
            if right is None or float(right.high) >= price:
                return "right_broken"
    else:
        price = float(bar.low)
        if price > min(float(b.low) for b in cur):
            return "not_15m_extreme"
        holders = [b for b in cur if float(b.low) == price]
        if int(holders[-1].timestamp) != int(pivot_ts):
            return "not_15m_extreme"
        if price <= min(float(b.low) for b in prev):
            return "not_weaker_15m"
        prior = _span(index, _floor(pivot_ts, M30) - M30, 6)
        if prior is None:
            return "missing_30m"
        if price < min(float(b.low) for b in prior):
            return "break_30m"
        for step in (1, 2):
            right = index.get(int(pivot_ts) + step * M5)
            if right is None or float(right.low) <= price:
                return "right_broken"
    return "ok"


def _pack(bar: Bar, side: str) -> dict:
    price = float(bar.high) if side == "short" else float(bar.low)
    ts = int(bar.timestamp)
    return {
        "side": side,
        "signal_key": f"{side}:{ts}:{price}",
        "pivot_time_ms": ts,
        "pivot_price": price,
        "pivot_kind": "peak" if side == "short" else "trough",
        "pivot_high": float(bar.high),
        "pivot_low": float(bar.low),
    }


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


def _setup_from_tz_pivots(state: SymbolState, now_ms: int) -> dict | None:
    """Pivot L15–L30 + 2 справа (как на графике) и фильтр 15м/30м для входа."""
    snap = snapshot_pivot_levels(state, "5", now_ms)
    if not snap:
        return None
    bars = closed_bars(state.bars_htf.get("5") or [], "5", now_ms)
    if len(bars) < 12:
        return None
    index = _index(bars)
    events: list[tuple[int, str]] = []
    for p in snap.get("peaks") or []:
        ts = int(p["time_ms"])
        if ts + 3 * M5 > int(now_ms):
            continue
        if index.get(ts + M5) is None or index.get(ts + 2 * M5) is None:
            continue
        if qualify_m5_pivot(index, ts, "short") == "ok":
            events.append((ts, "short"))
    for p in snap.get("troughs") or []:
        ts = int(p["time_ms"])
        if ts + 3 * M5 > int(now_ms):
            continue
        if index.get(ts + M5) is None or index.get(ts + 2 * M5) is None:
            continue
        if qualify_m5_pivot(index, ts, "long") == "ok":
            events.append((ts, "long"))
    if not events:
        return None
    events.sort(key=lambda x: x[0], reverse=True)
    ts, side = events[0]
    bar = index.get(ts)
    if bar is None:
        return None
    return _pack(bar, side)


def newest_pivot_reason(state: SymbolState, now_ms: int) -> str:
    """Причина по TZ-pivot (L15–L30), у которого уже две свечи справа."""
    snap = snapshot_pivot_levels(state, "5", now_ms)
    if not snap:
        return "no_bar"
    bars = closed_bars(state.bars_htf.get("5") or [], "5", now_ms)
    if len(bars) < 12:
        return "no_bar"
    index = _index(bars)
    fallback = "no_bar"
    for ts in _tz_pivot_times_ms(snap):
        if ts + 3 * M5 > int(now_ms):
            continue
        if index.get(ts + M5) is None or index.get(ts + 2 * M5) is None:
            continue
        reasons = [qualify_m5_pivot(index, ts, side) for side in ("short", "long")]
        if "ok" in reasons:
            return "ok"
        for reason in reasons:
            if reason != "not_15m_extreme":
                return reason
        fallback = "not_15m_extreme"
    return fallback


def m5_htf_setup(state: SymbolState, now_ms: int) -> dict | None:
    """Самый свежий TZ-pivot 5m (как LH/HL на графике) + подтверждение 15м/30м."""
    if not _meets_turnover(state):
        return None
    return _setup_from_tz_pivots(state, now_ms)


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
    prev = _span(index, open15 - M15, 3)
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


def opposite_appeared(
    state: SymbolState,
    now_ms: int,
    open_side: str,
    opened_at_ms: int,
    interval: str = "5",
) -> dict | None:
    """Противоположный L15–L30, вторая свеча которого закрылась уже после входа.

    Проверка выхода не привязана к 10 секундам: пивот остаётся поводом закрыть,
    пока сделка открыта. Подтверждение 15м/30м для выхода не нужно.
    """
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
