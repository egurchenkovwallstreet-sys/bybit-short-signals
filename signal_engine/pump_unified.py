"""Детект пампа: 1ч / 4ч / сутки на часовых и 4-часовых свечах.

Короткий: +20% за 1ч и объём ≥×3 к среднему.
Средний: +40% за 4ч и объём ≥×5.
Длинный: +60% за сутки и объём ≥×8.
На H4 и D1 — экстремумы за 30 дней (уровни, не пик пампа).

Пороги — PUMP_UNIFIED_* в config.py. Paper find_pump не читает этот модуль.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import config
from signal_engine.pump_phases import drawdown_from_peak_pct
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars


def price_24h_pct(raw: float | None) -> float | None:
    """Bybit price24hPcnt — доля (0.35 = +35%)."""
    if raw is None:
        return None
    if abs(raw) <= 2.0:
        return raw * 100.0
    return raw


HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
_TF_MS = {"60": HOUR_MS, "240": 4 * HOUR_MS, "D": DAY_MS}


@dataclass
class EpisodeDraft:
    symbol: str
    valley_price: float
    valley_ts: int
    peak_price: float
    peak_ts: int
    growth_pct: float
    pump_class: str
    volume_ratio: float | None
    source: str
    h4_high: float | None = None
    h4_high_ts: int | None = None
    h4_low: float | None = None
    h4_low_ts: int | None = None
    d1_high: float | None = None
    d1_high_ts: int | None = None
    d1_low: float | None = None
    d1_low_ts: int | None = None
    extra: dict = field(default_factory=dict)


def meets_unified_turnover(state: SymbolState) -> bool:
    turnover = state.turnover_24h_usdt
    if turnover is None:
        return True
    return turnover >= config.PUMP_UNIFIED_MIN_TURNOVER_USDT


def window_ms(pump_class: str) -> int:
    if pump_class == "medium":
        return int(config.PUMP_UNIFIED_WINDOW_HOURS_MEDIUM) * HOUR_MS
    if pump_class == "long":
        return int(config.PUMP_UNIFIED_WINDOW_HOURS_LONG) * HOUR_MS
    return int(config.PUMP_UNIFIED_WINDOW_HOURS_FAST) * HOUR_MS


def min_growth_pct(pump_class: str) -> float:
    if pump_class == "medium":
        return config.PUMP_UNIFIED_GROWTH_MIN_MEDIUM
    if pump_class == "long":
        return config.PUMP_UNIFIED_GROWTH_MIN_LONG
    return config.PUMP_UNIFIED_GROWTH_MIN_FAST


def min_volume_ratio(pump_class: str) -> float:
    if pump_class == "fast":
        return config.PUMP_UNIFIED_VOLUME_MIN_FAST
    if pump_class == "medium":
        return config.PUMP_UNIFIED_VOLUME_MIN_MEDIUM
    return config.PUMP_UNIFIED_VOLUME_MIN_LONG


def max_drawdown_pct() -> float:
    return config.PUMP_UNIFIED_MAX_DRAWDOWN_PCT


def should_remove_after_peak_drawdown(state: SymbolState | None, peak_price: float) -> bool:
    if state is None or peak_price <= 0:
        return False
    price = state.last_price
    if price is None or price <= 0:
        return False
    return drawdown_from_peak_pct(price, peak_price) >= max_drawdown_pct()


def _median_volume(bars: list[Bar]) -> float | None:
    vols = [float(b.volume) for b in bars if b.volume and b.volume > 0]
    if not vols:
        return None
    return float(statistics.median(vols))


def volume_ratio_median_24h_48h(state: SymbolState, now_ms: int) -> float | None:
    """Совместимость: медиана объёма 24h / медиана 48h до этого (1h)."""
    bars_1h = _tf_bars(state, "60", now_ms)
    if len(bars_1h) < 72:
        return None
    med_leg = _median_volume(bars_1h[-24:])
    med_pre = _median_volume(bars_1h[-72:-24])
    if med_leg and med_pre and med_pre > 0:
        return med_leg / med_pre
    return None


def _aggregate(src: list[Bar], out_ms: int) -> list[Bar]:
    buckets: dict[int, Bar] = {}
    for bar in src:
        t = (int(bar.timestamp) // out_ms) * out_ms
        prev = buckets.get(t)
        if prev is None:
            buckets[t] = Bar(t, bar.open, bar.high, bar.low, bar.close, bar.volume)
            continue
        buckets[t] = Bar(
            t,
            prev.open,
            max(prev.high, bar.high),
            min(prev.low, bar.low),
            bar.close,
            prev.volume + bar.volume,
        )
    return [buckets[k] for k in sorted(buckets)]


def _tf_bars(state: SymbolState, interval: str, now_ms: int) -> list[Bar]:
    native = closed_bars(state.bars_htf.get(interval) or [], interval, now_ms)
    if interval == "60":
        return native
    if len(native) >= 2:
        return native
    bars_1h = closed_bars(state.bars_htf.get("60") or [], "60", now_ms)
    if interval == "240":
        if len(bars_1h) >= 8:
            return _aggregate(bars_1h, 4 * HOUR_MS)
        return native
    if len(native) >= 1:
        return native
    bars_4h = _tf_bars(state, "240", now_ms)
    if len(bars_4h) >= 8:
        return _aggregate(bars_4h, DAY_MS)
    if len(bars_1h) >= 24:
        return _aggregate(bars_1h, DAY_MS)
    return native


def htf_extremes(
    bars: list[Bar],
    now_ms: int,
    days: int,
) -> tuple[float, int, float, int] | None:
    lo_ts = now_ms - days * DAY_MS
    window = [b for b in bars if lo_ts <= b.timestamp <= now_ms]
    if not window:
        return None
    hi = max(window, key=lambda b: b.high)
    lo = min(window, key=lambda b: b.low)
    if hi.high <= 0 or lo.low <= 0:
        return None
    return float(hi.high), int(hi.timestamp), float(lo.low), int(lo.timestamp)


def attach_30d_levels(state: SymbolState, now_ms: int, draft: EpisodeDraft) -> EpisodeDraft:
    days = int(config.PUMP_UNIFIED_LEVEL_LOOKBACK_DAYS)
    h4 = htf_extremes(_tf_bars(state, "240", now_ms), now_ms, days)
    if h4:
        draft.h4_high, draft.h4_high_ts, draft.h4_low, draft.h4_low_ts = h4
    d1 = htf_extremes(_tf_bars(state, "D", now_ms), now_ms, days)
    if d1:
        draft.d1_high, draft.d1_high_ts, draft.d1_low, draft.d1_low_ts = d1
    return draft


def _scan_windows(
    bars: list[Bar],
    *,
    window_bars: int,
    min_growth: float,
    min_vol: float,
    avg_bars: int,
    now_ms: int,
    max_age_ms: int,
    pump_class: str,
    source: str,
    symbol: str,
    last_price: float | None,
) -> list[EpisodeDraft]:
    if window_bars < 1 or len(bars) < avg_bars + window_bars:
        return []
    out: list[EpisodeDraft] = []
    last_i = len(bars) - window_bars
    for i in range(avg_bars, last_i + 1):
        window = bars[i : i + window_bars]
        peak_bar = max(window, key=lambda b: b.high)
        valley_bar = min(window, key=lambda b: b.low)
        if peak_bar.high <= 0 or valley_bar.low <= 0:
            continue
        if now_ms - int(peak_bar.timestamp) > max_age_ms:
            continue
        growth = (peak_bar.high / valley_bar.low - 1.0) * 100.0
        if growth < min_growth:
            continue
        prior = bars[i - avg_bars : i]
        med = _median_volume(prior)
        win_vol = sum(float(b.volume) for b in window if b.volume and b.volume > 0)
        if not med or med <= 0 or win_vol <= 0:
            continue
        vol_x = (win_vol / window_bars) / med
        if vol_x < min_vol:
            continue
        price = last_price or peak_bar.high
        if drawdown_from_peak_pct(price, peak_bar.high) >= max_drawdown_pct():
            continue
        out.append(
            EpisodeDraft(
                symbol=symbol,
                valley_price=float(valley_bar.low),
                valley_ts=int(valley_bar.timestamp),
                peak_price=float(peak_bar.high),
                peak_ts=int(peak_bar.timestamp),
                growth_pct=growth,
                pump_class=pump_class,
                volume_ratio=round(vol_x, 3),
                source=source,
            )
        )
    return out


def _class_specs() -> list[tuple[str, str, int, int, int]]:
    """(class, interval, window_bars, avg_bars, max_age_hours)."""
    return [
        (
            "fast",
            "60",
            1,
            int(config.PUMP_UNIFIED_VOL_AVG_BARS_1H),
            48,
        ),
        (
            "medium",
            "240",
            1,
            int(config.PUMP_UNIFIED_VOL_AVG_BARS_4H),
            120,
        ),
        (
            "long",
            "D",
            1,
            int(config.PUMP_UNIFIED_VOL_AVG_BARS_D),
            168,
        ),
    ]


def detect_unified_episodes(state: SymbolState, now_ms: int) -> list[EpisodeDraft]:
    if not meets_unified_turnover(state):
        return []
    collected: list[EpisodeDraft] = []
    bars_1h = _tf_bars(state, "60", now_ms)
    last = state.last_price

    for pump_class, interval, win_bars, avg_bars, max_age_h in _class_specs():
        bars = _tf_bars(state, interval, now_ms)
        collected.extend(
            _scan_windows(
                bars,
                window_bars=win_bars,
                min_growth=min_growth_pct(pump_class),
                min_vol=min_volume_ratio(pump_class),
                avg_bars=avg_bars,
                now_ms=now_ms,
                max_age_ms=max_age_h * HOUR_MS,
                pump_class=pump_class,
                source=f"htf_{interval}",
                symbol=state.symbol,
                last_price=last,
            )
        )

    if bars_1h:
        collected.extend(
            _scan_windows(
                bars_1h,
                window_bars=4,
                min_growth=min_growth_pct("medium"),
                min_vol=min_volume_ratio("medium"),
                avg_bars=int(config.PUMP_UNIFIED_VOL_AVG_BARS_1H),
                now_ms=now_ms,
                max_age_ms=120 * HOUR_MS,
                pump_class="medium",
                source="htf_60x4",
                symbol=state.symbol,
                last_price=last,
            )
        )
        collected.extend(
            _scan_windows(
                bars_1h,
                window_bars=24,
                min_growth=min_growth_pct("long"),
                min_vol=min_volume_ratio("long"),
                avg_bars=int(config.PUMP_UNIFIED_VOL_AVG_BARS_1H),
                now_ms=now_ms,
                max_age_ms=168 * HOUR_MS,
                pump_class="long",
                source="htf_60x24",
                symbol=state.symbol,
                last_price=last,
            )
        )

    best = _dedupe(collected)
    for draft in best:
        _stamp_peak_on_1h(bars_1h, draft, now_ms)
        attach_30d_levels(state, now_ms, draft)
    return best


def _dedupe(drafts: list[EpisodeDraft]) -> list[EpisodeDraft]:
    best: dict[tuple[str, str], EpisodeDraft] = {}
    for d in drafts:
        key = (d.symbol, d.pump_class)
        prev = best.get(key)
        if prev is None or d.growth_pct > prev.growth_pct:
            best[key] = d
    return list(best.values())


def _stamp_peak_on_1h(bars_1h: list[Bar], draft: EpisodeDraft, now_ms: int) -> None:
    """Время пика — часовая свеча, которая сделала хай, не open дневной/4h."""
    if not bars_1h or draft.peak_price <= 0:
        return
    lo = int(draft.valley_ts or 0)
    hits = [
        b
        for b in bars_1h
        if (lo <= 0 or b.timestamp >= lo)
        and b.timestamp <= now_ms
        and float(b.high) + 1e-12 >= float(draft.peak_price) * 0.999
    ]
    if not hits:
        return
    best = max(hits, key=lambda b: int(b.timestamp))
    draft.peak_ts = int(best.timestamp)
    if float(best.high) > draft.peak_price:
        draft.peak_price = float(best.high)


def htf_30d_levels(state: SymbolState, now_ms: int) -> dict:
    draft = EpisodeDraft(
        symbol=state.symbol,
        valley_price=0.0,
        valley_ts=0,
        peak_price=0.0,
        peak_ts=0,
        growth_pct=0.0,
        pump_class="fast",
        volume_ratio=None,
        source="levels",
    )
    attach_30d_levels(state, now_ms, draft)
    return {
        "h4_high": draft.h4_high,
        "h4_high_ts": draft.h4_high_ts,
        "h4_low": draft.h4_low,
        "h4_low_ts": draft.h4_low_ts,
        "d1_high": draft.d1_high,
        "d1_high_ts": draft.d1_high_ts,
        "d1_low": draft.d1_low,
        "d1_low_ts": draft.d1_low_ts,
    }


def detect_unified_episode(state: SymbolState, now_ms: int) -> EpisodeDraft | None:
    drafts = detect_unified_episodes(state, now_ms)
    if not drafts:
        return None
    return max(drafts, key=lambda d: (int(d.peak_ts), d.growth_pct))


def symbol_has_unified_pump(state: SymbolState, now_ms: int) -> bool:
    return bool(detect_unified_episodes(state, now_ms))
