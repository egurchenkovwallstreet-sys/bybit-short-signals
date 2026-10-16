"""Пылесос (LH-скан): до пяти LH на выбранном TF; в список — цена ниже 3 последних вершин."""

from __future__ import annotations

import config
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars, pivot_highs_asymmetric, pivot_lows_asymmetric

_INTERVAL_MS = {
    "5": 300_000,
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
    pivot_left: int | None = None,
    pivot_right: int | None = None,
) -> list[dict]:
    """До `count` последних pivot-high, каждый ниже предыдущего в цепочке (от старых к новым)."""
    n = count if count is not None else config.VACUUM_LH_PEAK_COUNT
    pl = pivot_left if pivot_left is not None else config.VACUUM_LH_PIVOT_LEFT
    pr = pivot_right if pivot_right is not None else config.VACUUM_LH_PIVOT_RIGHT
    lookback_ms = config.VACUUM_LH_LOOKBACK_DAYS * 24 * 3_600_000
    closed = closed_bars(bars, interval, now_ms)
    segment = [b for b in closed if b.timestamp >= now_ms - lookback_ms]
    peaks = pivot_highs_asymmetric(segment, pl, pr)
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


def last_higher_low_troughs(
    bars: list[Bar],
    interval: str,
    now_ms: int,
    *,
    count: int | None = None,
    pivot_left: int | None = None,
    pivot_right: int | None = None,
) -> list[dict]:
    """До `count` последних pivot-low, каждый выше предыдущего в цепочке (HL, от старых к новым)."""
    n = count if count is not None else config.VACUUM_LH_PEAK_COUNT
    pl = pivot_left if pivot_left is not None else config.VACUUM_LH_PIVOT_LEFT
    pr = pivot_right if pivot_right is not None else config.VACUUM_LH_PIVOT_RIGHT
    lookback_ms = config.VACUUM_LH_LOOKBACK_DAYS * 24 * 3_600_000
    closed = closed_bars(bars, interval, now_ms)
    segment = [b for b in closed if b.timestamp >= now_ms - lookback_ms]
    troughs = pivot_lows_asymmetric(segment, pl, pr)
    if len(troughs) < 2:
        return []
    chain: list[dict] = [troughs[-1]]
    for p in reversed(troughs[:-1]):
        if float(p["price"]) < float(chain[0]["price"]):
            chain.insert(0, p)
        if len(chain) >= n:
            break
    if len(chain) < 2:
        return []
    if len(chain) > n:
        chain = chain[-n:]
    return chain


def _pivot_match_key(p: dict) -> tuple[int, float]:
    t = int(p.get("time_ms") or p.get("time") or 0)
    return (t, round(float(p["price"]), 8))


def _peak_match_key(p: dict) -> tuple[int, float]:
    return _pivot_match_key(p)


def lh_peaks_for_interval(state: SymbolState, now_ms: int, interval: str) -> list[dict]:
    """Цепочка LH на TF (без фильтра «цена ниже N вершин»)."""
    if interval not in config.VACUUM_LH_CONFLUENCE_INTERVALS:
        return []
    bars = _bars_for_interval(state, interval)
    if len(bars) < _min_bars(interval):
        return []
    chain = last_lower_high_peaks(bars, interval, now_ms)
    if not chain:
        return []
    return project_peaks_to_chart(chain, interval)


def hl_troughs_for_interval(state: SymbolState, now_ms: int, interval: str) -> list[dict]:
    if interval not in config.VACUUM_LH_CONFLUENCE_INTERVALS:
        return []
    bars = _bars_for_interval(state, interval)
    if len(bars) < _min_bars(interval):
        return []
    chain = last_higher_low_troughs(bars, interval, now_ms)
    if not chain:
        return []
    return project_troughs_to_chart(chain, interval)


def confluence_index(peaks_by_interval: dict[str, list[dict]]) -> dict[tuple[int, float], list[str]]:
    """Ключ (time_ms, price) → список TF, где есть такая же вершина."""
    idx: dict[tuple[int, float], list[str]] = {}
    for interval, peaks in peaks_by_interval.items():
        for p in peaks:
            key = _pivot_match_key(p)
            bucket = idx.setdefault(key, [])
            if interval not in bucket:
                bucket.append(interval)
    return idx


def apply_pivot_confluence(points: list[dict], index: dict[tuple[int, float], list[str]]) -> list[dict]:
    out: list[dict] = []
    for p in points:
        key = _pivot_match_key(p)
        matches = list(index.get(key) or [])
        matches.sort(key=lambda x: (0 if x.isdigit() else 1, int(x) if x.isdigit() else x))
        item = dict(p)
        item["tf_match_count"] = len(matches)
        item["tf_matches"] = matches
        item["confluence"] = len(matches) >= 2
        out.append(item)
    return out


apply_peak_confluence = apply_pivot_confluence


def enrich_peaks_confluence(state: SymbolState, now_ms: int, peaks: list[dict]) -> list[dict]:
    by_iv = {
        iv: lh_peaks_for_interval(state, now_ms, iv) for iv in config.VACUUM_LH_CONFLUENCE_INTERVALS
    }
    index = confluence_index(by_iv)
    return apply_pivot_confluence(peaks, index)


def enrich_troughs_confluence(state: SymbolState, now_ms: int, troughs: list[dict]) -> list[dict]:
    by_iv = {
        iv: hl_troughs_for_interval(state, now_ms, iv) for iv in config.VACUUM_LH_CONFLUENCE_INTERVALS
    }
    index = confluence_index(by_iv)
    return apply_pivot_confluence(troughs, index)


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


def project_troughs_to_chart(troughs: list[dict], chart_interval: str) -> list[dict]:
    """HL-минимумы для графика (та же привязка времени, что у вершин)."""
    step = _INTERVAL_MS.get(chart_interval, _INTERVAL_MS["60"])
    out: list[dict] = []
    for i, p in enumerate(troughs, start=1):
        t = int(p["time"])
        t_chart = (t // step) * step
        out.append(
            {
                "index": i,
                "price": round(float(p["price"]), 8),
                "time_ms": t,
                "time_chart_ms": t_chart,
                "hl_interval": chart_interval,
            }
        )
    return out


def classify_lh_hl_structure(peaks: list[dict], troughs: list[dict]) -> str:
    """down | up | mixed — по последним 3 вершинам и 3 минимумам цепочки."""
    if len(peaks) < 3 or len(troughs) < 3:
        return "mixed"
    peak_tail = [float(p["price"]) for p in peaks[-3:]]
    trough_tail = [float(t["price"]) for t in troughs[-3:]]

    def strictly_down(values: list[float]) -> bool:
        return values[0] > values[1] > values[2]

    def strictly_up(values: list[float]) -> bool:
        return values[0] < values[1] < values[2]

    if strictly_down(peak_tail) and strictly_down(trough_tail):
        return "down"
    if strictly_up(peak_tail) and strictly_up(trough_tail):
        return "up"
    return "mixed"


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
    projected = enrich_peaks_confluence(state, now_ms, project_peaks_to_chart(peaks, lh_interval))
    troughs_raw = last_higher_low_troughs(bars, lh_interval, now_ms)
    projected_troughs = (
        enrich_troughs_confluence(state, now_ms, project_troughs_to_chart(troughs_raw, lh_interval))
        if len(troughs_raw) >= 2
        else []
    )
    nearest = projected[-1]["price"]
    gap_pct = (nearest - float(last)) / nearest * 100.0 if nearest > 0 else 0.0
    return {
        "symbol": state.symbol,
        "last_price": float(last),
        "turnover_24h_usdt": float(state.turnover_24h_usdt or 0),
        "lh_interval": lh_interval,
        "peak_count": len(projected),
        "peaks": projected,
        "trough_count": len(projected_troughs),
        "troughs": projected_troughs,
        "structure_trend": classify_lh_hl_structure(projected, projected_troughs),
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
