"""Пылесос (LH-скан): pivot L15–L30, 2 справа, gap ≥30 (VACUUM_LH_PIVOT_*); цепочки LH/HL."""

from __future__ import annotations

import config
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import (
    closed_bars,
    filter_pivots_min_bar_gap,
    pivot_highs_floating_left,
    pivot_lows_floating_left,
)

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


def _range_pct(bars: list[Bar], last_price: float) -> float | None:
    if last_price <= 0 or not bars:
        return None
    high = max(float(b.high) for b in bars)
    low = min(float(b.low) for b in bars)
    if high <= 0 or low <= 0 or high < low:
        return None
    return (high - low) / last_price * 100.0


def hour_range_pct(state: SymbolState, now_ms: int, last_price: float | None = None) -> float | None:
    """Размах цены за последние 60 мин, % от текущей цены. Нет окна — None."""
    price = float(last_price if last_price is not None else (state.last_price or 0))
    if price <= 0:
        return None
    start = int(now_ms) - 3_600_000
    minutes = [
        b
        for b in (state.bars_1m or [])
        if start - 60_000 <= int(b.timestamp) <= int(now_ms)
    ]
    if len(minutes) >= config.VACUUM_LH_HOUR_MIN_1M_BARS:
        return _range_pct(minutes, price)
    fives = [
        b
        for b in (state.bars_htf.get("5") or [])
        if start - 300_000 <= int(b.timestamp) <= int(now_ms)
    ]
    if len(fives) >= config.VACUUM_LH_HOUR_MIN_5M_BARS:
        return _range_pct(fives, price)
    return None


def _meets_hour_range(state: SymbolState, now_ms: int, last_price: float) -> tuple[bool, float | None]:
    pct = hour_range_pct(state, now_ms, last_price)
    if pct is None:
        return False, None
    return pct + 1e-12 >= config.VACUUM_LH_HOUR_RANGE_PCT, pct


def _bars_for_interval(state: SymbolState, interval: str) -> list[Bar]:
    if interval == "1":
        return state.bars_1m
    return state.bars_htf.get(interval) or []


def _min_bars(interval: str) -> int:
    return int(config.VACUUM_LH_MIN_BARS.get(interval, config.VACUUM_LH_MIN_1H_BARS))


def bars_from_candle_rows(rows: list[dict]) -> list[Bar]:
    bars: list[Bar] = []
    for c in rows or []:
        ts = int(c.get("timestamp") or 0)
        if ts <= 0:
            continue
        bars.append(
            Bar(
                ts,
                float(c.get("open") or 0),
                float(c.get("high") or 0),
                float(c.get("low") or 0),
                float(c.get("close") or 0),
                float(c.get("volume") or 0),
                from_kline=True,
            )
        )
    return bars


def _pivot_key_raw(p: dict) -> tuple[int, float]:
    return (int(p["time"]), round(float(p["price"]), 8))


def _pivot_bar_index(segment: list[Bar], p: dict) -> int:
    bi = int(p.get("bar_index", -1))
    if bi >= 0:
        return bi
    t = int(p["time"])
    for idx, b in enumerate(segment):
        if int(b.timestamp) == t:
            return idx
    return -1


def _pivot_broken_by_price(segment: list[Bar], p: dict, kind: str, confirm_right: int) -> bool:
    """После confirm_right свечей справа уровень pivot пробит телом последующих баров."""
    bi = _pivot_bar_index(segment, p)
    if bi < 0:
        return False
    start = bi + confirm_right + 1
    if start >= len(segment):
        return False
    price = float(p["price"])
    for b in segment[start:]:
        if kind == "peak":
            if float(b.high) > price + 1e-12:
                return True
        elif float(b.low) < price - 1e-12:
            return True
    return False


def _split_peaks_active_ghost(
    segment: list[Bar], pl: int, pl_max: int, pr: int, min_gap: int
) -> tuple[list[dict], list[dict]]:
    from signal_engine.swing_highs import filter_pivots_min_bar_gap_split

    raw = pivot_highs_floating_left(segment, pl, pl_max, pr)
    filtered, gap_replaced = filter_pivots_min_bar_gap_split(raw, min_gap, kind="peak")
    confirm = config.VACUUM_LH_PIVOT_RIGHT
    active = [p for p in filtered if not _pivot_broken_by_price(segment, p, "peak", confirm)]
    broken = [p for p in filtered if _pivot_broken_by_price(segment, p, "peak", confirm)]
    ghost_map: dict[tuple[int, float], dict] = {}
    for p in broken + gap_replaced:
        ghost_map[_pivot_key_raw(p)] = p
    return active, list(ghost_map.values())


def _split_troughs_active_ghost(
    segment: list[Bar], pl: int, pl_max: int, pr: int, min_gap: int
) -> tuple[list[dict], list[dict]]:
    from signal_engine.swing_highs import filter_pivots_min_bar_gap_split

    raw = pivot_lows_floating_left(segment, pl, pl_max, pr)
    filtered, gap_replaced = filter_pivots_min_bar_gap_split(raw, min_gap, kind="trough")
    confirm = config.VACUUM_LH_PIVOT_RIGHT
    active = [p for p in filtered if not _pivot_broken_by_price(segment, p, "trough", confirm)]
    broken = [p for p in filtered if _pivot_broken_by_price(segment, p, "trough", confirm)]
    ghost_map: dict[tuple[int, float], dict] = {}
    for p in broken + gap_replaced:
        ghost_map[_pivot_key_raw(p)] = p
    return active, list(ghost_map.values())


# На графике — не весь lookback, иначе 5m за 14d забит «мёртвыми» pivot.
_VACUUM_CHART_GHOST_MAX = 16


def _trim_chart_ghosts(ghost: list[dict]) -> list[dict]:
    if len(ghost) <= _VACUUM_CHART_GHOST_MAX:
        return ghost
    ghost = sorted(ghost, key=lambda p: int(p.get("time") or 0))
    return ghost[-_VACUUM_CHART_GHOST_MAX:]


def _filtered_pivot_highs(segment: list[Bar], pl: int, pl_max: int, pr: int) -> list[dict]:
    """Стратегия / скан: только pivot, не перебитые после confirm."""
    gap = config.VACUUM_LH_PIVOT_MIN_GAP
    active, _ = _split_peaks_active_ghost(segment, pl, pl_max, pr, gap)
    return active


def _filtered_pivot_lows(segment: list[Bar], pl: int, pl_max: int, pr: int) -> list[dict]:
    gap = config.VACUUM_LH_PIVOT_MIN_GAP
    active, _ = _split_troughs_active_ghost(segment, pl, pl_max, pr, gap)
    return active


def _chart_pivot_highs_filtered(segment: list[Bar], pl: int, pl_max: int, pr: int) -> tuple[list[dict], list[dict]]:
    """График: все подтверждённые экстремумы после gap; ghost — только вытесненные в кластере."""
    from signal_engine.swing_highs import filter_pivots_min_bar_gap_split

    gap = config.VACUUM_LH_PIVOT_MIN_GAP
    raw = pivot_highs_floating_left(segment, pl, pl_max, pr)
    return filter_pivots_min_bar_gap_split(raw, gap, kind="peak")


def _chart_pivot_lows_filtered(segment: list[Bar], pl: int, pl_max: int, pr: int) -> tuple[list[dict], list[dict]]:
    from signal_engine.swing_highs import filter_pivots_min_bar_gap_split

    gap = config.VACUUM_LH_PIVOT_MIN_GAP
    raw = pivot_lows_floating_left(segment, pl, pl_max, pr)
    return filter_pivots_min_bar_gap_split(raw, gap, kind="trough")


def _ghost_pivot_highs(segment: list[Bar], pl: int, pl_max: int, pr: int) -> list[dict]:
    _, gap_replaced = _chart_pivot_highs_filtered(segment, pl, pl_max, pr)
    return gap_replaced


def _ghost_pivot_lows(segment: list[Bar], pl: int, pl_max: int, pr: int) -> list[dict]:
    _, gap_replaced = _chart_pivot_lows_filtered(segment, pl, pl_max, pr)
    return gap_replaced


def _lookback_segment(bars: list[Bar], interval: str, now_ms: int) -> list[Bar]:
    lookback_ms = config.VACUUM_LH_LOOKBACK_DAYS * 24 * 3_600_000
    closed = closed_bars(bars, interval, now_ms)
    return [b for b in closed if b.timestamp >= now_ms - lookback_ms]


def all_anchor_peaks(bars: list[Bar], interval: str, now_ms: int) -> list[dict]:
    """Все pivot-high за VACUUM_LH_LOOKBACK_DAYS, привязка к time_ms свечи."""
    segment = _lookback_segment(bars, interval, now_ms)
    if not segment:
        return []
    pl = config.VACUUM_LH_PIVOT_LEFT
    pl_max = config.VACUUM_LH_PIVOT_LEFT_MAX
    pr = config.VACUUM_LH_PIVOT_RIGHT
    raw = _filtered_pivot_highs(segment, pl, pl_max, pr)
    raw.sort(key=lambda p: int(p["time"]))
    return project_peaks_to_chart(raw, interval)


def all_anchor_troughs(bars: list[Bar], interval: str, now_ms: int) -> list[dict]:
    segment = _lookback_segment(bars, interval, now_ms)
    if not segment:
        return []
    pl = config.VACUUM_LH_PIVOT_LEFT
    pl_max = config.VACUUM_LH_PIVOT_LEFT_MAX
    pr = config.VACUUM_LH_PIVOT_RIGHT
    raw = _filtered_pivot_lows(segment, pl, pl_max, pr)
    raw.sort(key=lambda p: int(p["time"]))
    return project_troughs_to_chart(raw, interval)


def ghost_anchor_peaks(bars: list[Bar], interval: str, now_ms: int) -> list[dict]:
    """Перебитые/вытесненные pivot-high — только для графика, не для стратегии."""
    segment = _lookback_segment(bars, interval, now_ms)
    if not segment:
        return []
    pl = config.VACUUM_LH_PIVOT_LEFT
    pl_max = config.VACUUM_LH_PIVOT_LEFT_MAX
    pr = config.VACUUM_LH_PIVOT_RIGHT
    ghost = _trim_chart_ghosts(_ghost_pivot_highs(segment, pl, pl_max, pr))
    ghost.sort(key=lambda p: int(p["time"]))
    return project_peaks_to_chart(ghost, interval)


def ghost_anchor_troughs(bars: list[Bar], interval: str, now_ms: int) -> list[dict]:
    segment = _lookback_segment(bars, interval, now_ms)
    if not segment:
        return []
    pl = config.VACUUM_LH_PIVOT_LEFT
    pl_max = config.VACUUM_LH_PIVOT_LEFT_MAX
    pr = config.VACUUM_LH_PIVOT_RIGHT
    ghost = _trim_chart_ghosts(_ghost_pivot_lows(segment, pl, pl_max, pr))
    ghost.sort(key=lambda p: int(p["time"]))
    return project_troughs_to_chart(ghost, interval)


def chart_anchor_peaks(bars: list[Bar], interval: str, now_ms: int) -> list[dict]:
    """Якоря для графика: реальные pivot-high после gap (в т.ч. позже перебитые)."""
    segment = _lookback_segment(bars, interval, now_ms)
    if not segment:
        return []
    pl = config.VACUUM_LH_PIVOT_LEFT
    pl_max = config.VACUUM_LH_PIVOT_LEFT_MAX
    pr = config.VACUUM_LH_PIVOT_RIGHT
    filtered, _ = _chart_pivot_highs_filtered(segment, pl, pl_max, pr)
    filtered.sort(key=lambda p: int(p["time"]))
    return project_peaks_to_chart(filtered, interval)


def chart_anchor_troughs(bars: list[Bar], interval: str, now_ms: int) -> list[dict]:
    segment = _lookback_segment(bars, interval, now_ms)
    if not segment:
        return []
    pl = config.VACUUM_LH_PIVOT_LEFT
    pl_max = config.VACUUM_LH_PIVOT_LEFT_MAX
    pr = config.VACUUM_LH_PIVOT_RIGHT
    filtered, _ = _chart_pivot_lows_filtered(segment, pl, pl_max, pr)
    filtered.sort(key=lambda p: int(p["time"]))
    return project_troughs_to_chart(filtered, interval)


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
    pl_max = config.VACUUM_LH_PIVOT_LEFT_MAX
    pr = pivot_right if pivot_right is not None else config.VACUUM_LH_PIVOT_RIGHT
    segment = _lookback_segment(bars, interval, now_ms)
    peaks = _filtered_pivot_highs(segment, pl, pl_max, pr)
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
    pl_max = config.VACUUM_LH_PIVOT_LEFT_MAX
    pr = pivot_right if pivot_right is not None else config.VACUUM_LH_PIVOT_RIGHT
    segment = _lookback_segment(bars, interval, now_ms)
    troughs = _filtered_pivot_lows(segment, pl, pl_max, pr)
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


def union_pivot_points(*groups: list | None) -> list[dict]:
    """Склеить pivot по (time_ms, price). Новый экстремум скана не затирает старые."""
    merged: dict[tuple[int, float], dict] = {}
    for group in groups:
        for raw in group or []:
            if not isinstance(raw, dict) or raw.get("price") is None:
                continue
            key = _pivot_match_key(raw)
            prev = merged.get(key)
            if prev is None:
                merged[key] = dict(raw)
                continue
            item = dict(prev)
            for field, value in raw.items():
                if value in (None, "", []):
                    continue
                item[field] = value
            prev_ls = int(prev.get("left_strength") or 0)
            raw_ls = int(raw.get("left_strength") or 0)
            item["left_strength"] = prev_ls if prev_ls > 0 else raw_ls
            if int(prev.get("tf_match_count") or 0) > int(raw.get("tf_match_count") or 0):
                item["tf_match_count"] = prev.get("tf_match_count")
                item["tf_matches"] = prev.get("tf_matches")
                item["confluence"] = prev.get("confluence")
                if prev.get("index"):
                    item["index"] = prev.get("index")
            merged[key] = item
    out = list(merged.values())
    out.sort(key=lambda p: int(p.get("time_ms") or p.get("time") or 0))
    return out


def pivots_from_bars(bars: list[Bar], interval: str, now_ms: int) -> dict:
    """Все якоря TF и цепочка LH/HL для подписей. Те же правила, что у скана."""
    if not bars:
        return {
            "all_peaks": [],
            "all_troughs": [],
            "anchor_peaks": [],
            "anchor_troughs": [],
            "ghost_peaks": [],
            "ghost_troughs": [],
            "peaks": [],
            "troughs": [],
        }
    anchors_p = chart_anchor_peaks(bars, interval, now_ms)
    anchors_t = chart_anchor_troughs(bars, interval, now_ms)
    active_p = all_anchor_peaks(bars, interval, now_ms)
    active_t = all_anchor_troughs(bars, interval, now_ms)
    ghost_p = ghost_anchor_peaks(bars, interval, now_ms)
    ghost_t = ghost_anchor_troughs(bars, interval, now_ms)
    chain_p = last_lower_high_peaks(bars, interval, now_ms)
    chain_t = last_higher_low_troughs(bars, interval, now_ms)
    return {
        "all_peaks": active_p,
        "all_troughs": active_t,
        "anchor_peaks": anchors_p,
        "anchor_troughs": anchors_t,
        "ghost_peaks": ghost_p,
        "ghost_troughs": ghost_t,
        "peaks": project_peaks_to_chart(chain_p, interval) if chain_p else [],
        "troughs": project_troughs_to_chart(chain_t, interval) if len(chain_t) >= 2 else [],
    }


def chart_pivots_from_candles(rows: list[dict], interval: str, now_ms: int) -> dict:
    return pivots_from_bars(bars_from_candle_rows(rows), interval, now_ms)


def chart_pivots_for_symbols(
    states: dict[str, SymbolState],
    symbols: set[str] | list[str],
    interval: str,
    now_ms: int,
) -> dict[str, dict]:
    """Свежие якоря движка по монетам доски (короче истории графика, но сразу после подтверждения)."""
    out: dict[str, dict] = {}
    for sym in symbols:
        state = states.get(sym)
        if state is None:
            continue
        bars = _bars_for_interval(state, interval)
        if len(bars) < _min_bars(interval):
            continue
        out[sym] = pivots_from_bars(bars, interval, now_ms)
    return out


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
                "left_strength": int(p.get("left_strength") or 0),
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
                "left_strength": int(p.get("left_strength") or 0),
            }
        )
    return out


VACUUM_LH_STRUCTURE_INTERVAL = "240"


def structure_trend_on_interval(state: SymbolState, now_ms: int, interval: str) -> str:
    """Колонки списка: последние 3 LH + 3 HL на заданном TF (по умолчанию 4H)."""
    if interval not in config.VACUUM_LH_CONFLUENCE_INTERVALS:
        return "mixed"
    bars = _bars_for_interval(state, interval)
    if len(bars) < _min_bars(interval):
        return "mixed"
    peaks = last_lower_high_peaks(bars, interval, now_ms)
    troughs_raw = last_higher_low_troughs(bars, interval, now_ms)
    if len(peaks) < 3 or len(troughs_raw) < 3:
        return "mixed"
    projected = project_peaks_to_chart(peaks, interval)
    projected_troughs = project_troughs_to_chart(troughs_raw, interval)
    return classify_lh_hl_structure(projected, projected_troughs)


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
    hour_ok, hour_pct = _meets_hour_range(state, now_ms, float(last))
    if not hour_ok:
        return None
    bars = _bars_for_interval(state, lh_interval)
    if len(bars) < _min_bars(lh_interval):
        return None
    all_peaks = all_anchor_peaks(bars, lh_interval, now_ms)
    all_troughs = all_anchor_troughs(bars, lh_interval, now_ms)
    peaks = last_lower_high_peaks(bars, lh_interval, now_ms)
    projected = (
        enrich_peaks_confluence(state, now_ms, project_peaks_to_chart(peaks, lh_interval)) if peaks else []
    )
    troughs_raw = last_higher_low_troughs(bars, lh_interval, now_ms)
    projected_troughs = (
        enrich_troughs_confluence(state, now_ms, project_troughs_to_chart(troughs_raw, lh_interval))
        if len(troughs_raw) >= 2
        else []
    )
    nearest = projected[-1]["price"] if projected else (all_peaks[-1]["price"] if all_peaks else float(last))
    gap_pct = (nearest - float(last)) / nearest * 100.0 if nearest and nearest > 0 else 0.0
    return {
        "symbol": state.symbol,
        "last_price": float(last),
        "turnover_24h_usdt": float(state.turnover_24h_usdt or 0),
        "lh_interval": lh_interval,
        "peak_count": len(projected),
        "peaks": projected,
        "all_peaks": all_peaks,
        "trough_count": len(projected_troughs),
        "troughs": projected_troughs,
        "all_troughs": all_troughs,
        "structure_trend": structure_trend_on_interval(
            state, now_ms, VACUUM_LH_STRUCTURE_INTERVAL
        ),
        "nearest_peak_price": nearest,
        "gap_to_nearest_pct": round(gap_pct, 2),
        "hour_range_pct": round(float(hour_pct or 0.0), 2),
        "updated_at": now_ms,
    }


def build_vacuum_lh_board(
    states: dict[str, SymbolState],
    now_ms: int,
    lh_interval: str = "60",
    live_store: object | None = None,
) -> dict:
    from signal_engine.vacuum_lh_live import enrich_board_signals

    signals: list[dict] = []
    for state in states.values():
        if not _meets_turnover(state):
            continue
        row = scan_symbol(state, now_ms, lh_interval)
        if row is not None:
            signals.append(row)
    signals = enrich_board_signals(signals, live_store)
    signals.sort(
        key=lambda r: (
            -int(r.get("live_pin_seq") or 0),
            -float(r.get("turnover_24h_usdt") or 0),
            r["symbol"],
        ),
    )
    return {"type": "vacuum_lh_board", "timestamp": now_ms, "data": {"interval": lh_interval, "signals": signals}}


def build_vacuum_lh_boards(
    states: dict[str, SymbolState],
    now_ms: int,
    live_store: object | None = None,
) -> dict:
    """Все TF одним сообщением — клиент переключает без повторного скана."""
    if live_store is not None:
        live_store.update(states, now_ms)
    intervals: dict[str, list[dict]] = {}
    for lh_interval in config.VACUUM_LH_INTERVALS:
        board = build_vacuum_lh_board(states, now_ms, lh_interval, live_store)
        intervals[lh_interval] = board["data"]["signals"]
    symbols = {str(row.get("symbol") or "") for rows in intervals.values() for row in rows}
    symbols.discard("")
    return {
        "type": "vacuum_lh_board",
        "timestamp": now_ms,
        "data": {
            "intervals": intervals,
            "default_interval": config.VACUUM_LH_DEFAULT_INTERVAL,
            "chart_pivots": {"5": chart_pivots_for_symbols(states, symbols, "5", now_ms)},
        },
    }
