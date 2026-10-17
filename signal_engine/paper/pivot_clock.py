"""Часы pivot: 5m вход на 3-й свече справа; 15m — 10 с после 2-й подтверждающей.

БАБЛОСОС / Пылесос 5: вход только пока открыта 3-я 5m после экстремума.
Пылесос 15: вход в 10 с после закрытия 2-й 15m справа от экстремума.
"""

from __future__ import annotations

import config
from signal_engine.state import SymbolState
from signal_engine.swing_highs import closed_bars, pivot_highs_floating_left, pivot_lows_floating_left
from signal_engine.vacuum_lh import _bars_for_interval, _meets_turnover, _min_bars

_STEP = {"5": 300_000, "15": 900_000, "30": 1_800_000, "60": 3_600_000}


def bar_step_ms(interval: str) -> int:
    return _STEP.get(interval, 300_000)


def second_bar_close_ms(pivot_time_ms: int, interval: str = "5") -> int:
    """Момент закрытия второй свечи справа от экстремума (open экстремума + 3 шага)."""
    step = bar_step_ms(interval)
    right = config.VACUUM_LH_PIVOT_RIGHT
    return int(pivot_time_ms) + (right + 1) * step


def third_bar_open_ms(pivot_time_ms: int, interval: str = "5") -> int:
    """Open 3-й 5m-свечи после пивота (1-я и 2-я справа уже закрыты)."""
    return int(pivot_time_ms) + 3 * bar_step_ms(interval)


def third_bar_close_ms(pivot_time_ms: int, interval: str = "5") -> int:
    """Закрытие 3-й 5m-свечи после пивота."""
    return int(pivot_time_ms) + 4 * bar_step_ms(interval)


def entry_on_third_bar(pivot_time_ms: int, now_ms: int, interval: str = "5") -> bool:
    """Вход pyl/vps5: только пока 3-я 5m после pivot открыта."""
    if interval != "5":
        return False
    start = third_bar_open_ms(pivot_time_ms, interval)
    end = third_bar_close_ms(pivot_time_ms, interval)
    now = int(now_ms)
    return start <= now < end


def just_confirmed(pivot_time_ms: int, now_ms: int, interval: str = "5", slack_ms: int | None = None) -> bool:
    """Вторая свеча уже закрылась, и с этого момента прошло меньше slack."""
    slack = config.PAPER_PIVOT_CONFIRM_SLACK_MS if slack_ms is None else slack_ms
    close_at = second_bar_close_ms(pivot_time_ms, interval)
    now = int(now_ms)
    return close_at <= now < close_at + slack


def first_bar_waiting(pivot_time_ms: int, now_ms: int, interval: str = "5") -> bool:
    """Первая правая свеча закрыта, вторая ещё нет."""
    step = bar_step_ms(interval)
    first_close = int(pivot_time_ms) + 2 * step
    second_close = second_bar_close_ms(pivot_time_ms, interval)
    now = int(now_ms)
    return first_close <= now < second_close


def batch_has_closed_bar(candles: list[dict], close_ms: int, now_ms: int, step: int = 300_000) -> bool:
    """Свеча, которая должна была закрыться в close_ms, уже в ответе и не является текущей."""
    need = int(close_ms) - step
    times = [int(c.get("timestamp") or 0) for c in candles]
    if need not in times:
        return False
    if any(t >= int(close_ms) for t in times):
        return True
    return int(now_ms) >= int(close_ms) + 1500


def symbols_waiting_second_bar(states: dict[str, SymbolState], now_ms: int, interval: str = "5") -> set[str]:
    """Монеты, у которых экстремум уже выдержал одну закрытую свечу справа."""
    pl = config.VACUUM_LH_PIVOT_LEFT
    pl_max = config.VACUUM_LH_PIVOT_LEFT_MAX
    need = _min_bars(interval)
    out: set[str] = set()
    for symbol, state in states.items():
        if not state.last_price or not _meets_turnover(state):
            continue
        bars = _bars_for_interval(state, interval)
        if len(bars) < need:
            continue
        closed = closed_bars(bars, interval, now_ms)
        if len(closed) < pl + 2:
            continue
        points = pivot_highs_floating_left(closed, pl, pl_max, 1)
        points.extend(pivot_lows_floating_left(closed, pl, pl_max, 1))
        for point in points:
            if first_bar_waiting(int(point["time"]), now_ms, interval):
                out.add(symbol)
                break
    return out
