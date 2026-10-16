"""Пылесос (LH-скан): до пяти LH на выбранном TF; в список — цена ниже 3 последних вершин."""

from __future__ import annotations

import config
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars, pivot_highs

_INTERVAL_MS = {
    "15": 900_000,
    "30": 1_800_000,
    "60": 3_600_000,
    "240": 14_400_000,
}


def _meets_turnover(state: SymbolState) -> bool:
    turnover = state.turnover_24h_usdt
    if turnover is None:
        return False
    return turnover >= config.VACUUM_LH_MIN_TURNOVER_24H_USDT


def _bars_for_interval(state: SymbolState, interval: str) -> list[Bar]:
    if interval == "1":
        return state.bars_1m
    return state.bars_htf.get(interval) or []


def _min_bars(interval: str) -> int:
    return int(config.VACUUM_LH_MIN_BARS.get(interval, config.VACUUM_LH_MIN_1H_BARS))


def last_lower_high_peaks(
    bars: list[Bar],
    interval: str,
    now_ms: int,
    *,
    count: int | None = None,
    wing: int | None = None,
) -> list[dict]:
    """До `count` последних pivot-high, каждый ниже предыдущего в цепочке (от старых к новым)."""
    n = count if count is not None else config.VACUUM_LH_PEAK_COUNT
    w = wing if wing is not None else config.VACUUM_LH_PIVOT_WING
    lookback_ms = config.VACUUM_LH_LOOKBACK_DAYS * 24 * 3_600_000
    closed = closed_bars(bars, interval, now_ms)
    segment = [b for b in closed if b.timestamp >= now_ms - lookback_ms]
    peaks = pivot_highs(segment, w)
    if len(peaks) < 2:
        return []
    chain: list[dict] = [peaks[-1]]
    for p in reversed(peaks[:-1]):
        if float(p["price"]) > float(chain[0]["price"]):
            chain.insert(0, p)
        if len(chain) >= n:
            break
    if len(chain) < 2:
        return []
    if len(chain) > n:
        chain = chain[-n:]
    return chain


def project_peaks_to_chart(peaks: list[dict], chart_interval: str) -> list[dict]:
    """Привязка времени вершины к началу свечи графика."""
    step = _INTERVAL_MS.get(chart_interval, _INTERVAL_MS["60"])
    out: list[dict] = []
    for i, p in enumerate(peaks, start=1):
        t = int(p["time"])
        t_chart = (t // step) * step
        out.append(
            {
                "index": i,
                "price": round(float(p["price"]), 8),
                "time_ms": t,
                "time_chart_ms": t_chart,
                "lh_interval": chart_interval,
            }
        )
    return out


def price_below_recent_peaks(
    last_price: float,
    peaks: list[dict],
    *,
    last_n: int | None = None,
) -> bool:
    """Цена строго ниже каждой из `last_n` самых новых вершин цепочки."""
    n = last_n if last_n is not None else config.VACUUM_LH_PRICE_BELOW_LAST
    if not peaks or last_price is None or last_price <= 0 or n < 1:
        return False
    if len(peaks) < n:
        return False
    recent = peaks[-n:]
    return float(last_price) < min(float(p["price"]) for p in recent)


def scan_symbol(state: SymbolState, now_ms: int, lh_interval: str = "60") -> dict | None:
    if lh_interval not in config.VACUUM_LH_INTERVALS:
        return None
    if not _meets_turnover(state):
        return None
    last = state.last_price
    if last is None or last <= 0:
        return None
    bars = _bars_for_interval(state, lh_interval)
    if len(bars) < _min_bars(lh_interval):
        return None
    need = config.VACUUM_LH_PRICE_BELOW_LAST
    peaks = last_lower_high_peaks(bars, lh_interval, now_ms)
    if len(peaks) < need:
        return None
    if not price_below_recent_peaks(float(last), peaks):
        return None
    projected = project_peaks_to_chart(peaks, lh_interval)
    nearest = projected[-1]["price"]
    gap_pct = (nearest - float(last)) / nearest * 100.0 if nearest > 0 else 0.0
    return {
        "symbol": state.symbol,
        "last_price": float(last),
        "turnover_24h_usdt": float(state.turnover_24h_usdt or 0),
        "lh_interval": lh_interval,
        "peak_count": len(projected),
        "peaks": projected,
        "nearest_peak_price": nearest,
        "gap_to_nearest_pct": round(gap_pct, 2),
        "updated_at": now_ms,
    }


def build_vacuum_lh_board(
    states: dict[str, SymbolState],
    now_ms: int,
    lh_interval: str = "60",
) -> dict:
    signals: list[dict] = []
    for state in states.values():
        if not _meets_turnover(state):
            continue
        row = scan_symbol(state, now_ms, lh_interval)
        if row is not None:
            signals.append(row)
    signals.sort(key=lambda r: (-float(r["gap_to_nearest_pct"]), r["symbol"]))
    return {"type": "vacuum_lh_board", "timestamp": now_ms, "data": {"interval": lh_interval, "signals": signals}}


def build_vacuum_lh_boards(states: dict[str, SymbolState], now_ms: int) -> dict:
    """Все TF одним сообщением — клиент переключает без повторного скана."""
    intervals: dict[str, list[dict]] = {}
    for lh_interval in config.VACUUM_LH_INTERVALS:
        board = build_vacuum_lh_board(states, now_ms, lh_interval)
        intervals[lh_interval] = board["data"]["signals"]
    return {
        "type": "vacuum_lh_board",
        "timestamp": now_ms,
        "data": {"intervals": intervals, "default_interval": config.VACUUM_LH_DEFAULT_INTERVAL},
    }
