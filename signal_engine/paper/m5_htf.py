"""Экстремум 5м принимается только как экстремум своей 15м.

Шорт: high 15м ниже high предыдущей 15м и не выше high предыдущей 30м.
Лонг: low 15м выше low предыдущей 15м и не ниже low предыдущей 30м.
Две 5м справа экстремум не обновляют. Вход — на закрытии второй, это третья свеча.
"""

from __future__ import annotations

from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars
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


def newest_pivot_reason(state: SymbolState, now_ms: int) -> str:
    """Причина по самой свежей свече, у которой уже есть две справа."""
    bars = closed_bars(state.bars_htf.get("5") or [], "5", now_ms)
    if len(bars) < 12:
        return "no_bar"
    index = _index(bars)
    fallback = "no_bar"
    for bar in reversed(bars):
        ts = int(bar.timestamp)
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
    """Самый свежий экстремум 5м, который уже прошёл 15м, 30м и две свечи справа."""
    if not _meets_turnover(state):
        return None
    bars = closed_bars(state.bars_htf.get("5") or [], "5", now_ms)
    if len(bars) < 12:
        return None
    index = _index(bars)
    for bar in reversed(bars):
        ts = int(bar.timestamp)
        if ts + 3 * M5 > int(now_ms):
            continue
        for side in ("short", "long"):
            if qualify_m5_pivot(index, ts, side) == "ok":
                return _pack(bar, side)
    return None


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
