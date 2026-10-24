"""Единый детект пампа для лаборатории и всех досок (скан, 2×, поиск).

Все пороги — PUMP_UNIFIED_* в config.py. Лаборатория и watch-доски вызывают
detect_unified_episodes() для paper/кандидатов (UI «Анализ пампа» снят).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import config
from signal_engine.pump_history import history_pump_metrics
from signal_engine.paper.detect import merged_15m
from signal_engine.pump_phases import drawdown_from_peak_pct, pump_class_from_duration
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


def meets_unified_turnover(state: SymbolState) -> bool:
    turnover = state.turnover_24h_usdt
    if turnover is None:
        return True
    return turnover >= config.PUMP_UNIFIED_MIN_TURNOVER_USDT


def window_ms(pump_class: str) -> int:
    if pump_class == "medium":
        return config.PUMP_UNIFIED_WINDOW_DAYS_MEDIUM * DAY_MS
    if pump_class == "long":
        return config.PUMP_UNIFIED_MAX_AGE_DAYS * DAY_MS
    return config.PUMP_UNIFIED_WINDOW_HOURS_FAST * HOUR_MS


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
    """Убрать карточку: текущая цена отстаёт от пика пампа не меньше чем на порог %."""
    if state is None or peak_price <= 0:
        return False
    price = state.last_price
    if price is None or price <= 0:
        return False
    return drawdown_from_peak_pct(price, peak_price) >= max_drawdown_pct()


def volume_ratio_min_to_peak(
    bars: list[Bar],
    valley_ts: int,
    peak_ts: int,
    window_start_ms: int,
) -> float | None:
    duration = peak_ts - valley_ts
    if duration <= 0:
        return None
    base_start = valley_ts - duration
    if base_start < window_start_ms:
        return None
    leg_vol = sum(b.volume for b in bars if valley_ts <= b.timestamp <= peak_ts and b.volume > 0)
    if leg_vol <= 0:
        return None
    base_vol = sum(b.volume for b in bars if base_start <= b.timestamp < valley_ts and b.volume > 0)
    if base_vol <= 0:
        return None
    return leg_vol / base_vol


def _median_volume(bars: list[Bar]) -> float | None:
    vols = [float(b.volume) for b in bars if b.volume and b.volume > 0]
    if not vols:
        return None
    return float(statistics.median(vols))


def volume_ratio_median_24h_48h(state: SymbolState, now_ms: int) -> float | None:
    """Медиана объёма 24h / медиана 48h до этого (1h бары, иначе 15m)."""
    bars_1h = closed_bars(state.bars_htf.get("60") or [], "60", now_ms)
    if len(bars_1h) >= 72:
        last_24 = bars_1h[-24:]
        prev_48 = bars_1h[-72:-24]
        med_leg = _median_volume(last_24)
        med_pre = _median_volume(prev_48)
        if med_leg and med_pre and med_pre > 0:
            return med_leg / med_pre
    bars_15 = merged_15m(state)
    closed = [b for b in bars_15 if b.timestamp <= now_ms]
    if len(closed) < 96 + 48:
        return None
    last_96 = closed[-96:]
    prev_192 = closed[-96 - 192 : -96]
    med_leg = _median_volume(last_96)
    med_pre = _median_volume(prev_192)
    if med_leg and med_pre and med_pre > 0:
        return med_leg / med_pre
    return None


def _price_trend_ok(state: SymbolState, bars_15: list[Bar], now_ms: int) -> bool:
    """Не боковик: close выше, чем 72h назад, или ≥3 из 6 последних 15m бычьи."""
    closed = [b for b in bars_15 if b.timestamp <= now_ms]
    if len(closed) < 8:
        return True
    last = closed[-1]
    idx_72h = len(closed) - 1 - 288
    if idx_72h >= 0 and last.close >= closed[idx_72h].close:
        return True
    last6 = closed[-6:]
    green = sum(1 for b in last6 if b.close > b.open)
    return green >= 3


def _draft_valley_lookback(state: SymbolState, now_ms: int) -> EpisodeDraft | None:
    """Основной путь: дно за 7 сут → пик, рост и объём по правилам recall ~90%."""
    lookback = int(config.PUMP_UNIFIED_VALLEY_LOOKBACK_DAYS) * DAY_MS
    bars_1h = closed_bars(state.bars_htf.get("60") or [], "60", now_ms)
    bars_15 = merged_15m(state)
    if len(bars_1h) >= 48:
        recent = [b for b in bars_1h if now_ms - lookback <= b.timestamp <= now_ms]
        source = "valley_7d_1h"
    elif len(bars_15) >= 96:
        recent = [b for b in bars_15 if now_ms - lookback <= b.timestamp <= now_ms]
        source = "valley_7d_15m"
    else:
        return None
    if len(recent) < 4:
        return None
    valley_bar = min(recent, key=lambda b: b.low)
    after = [b for b in recent if b.timestamp >= valley_bar.timestamp]
    if len(after) < 2:
        return None
    peak_bar = max(after, key=lambda b: b.high)
    pump_class = _class_from_duration(valley_bar.timestamp, peak_bar.timestamp)
    growth = (peak_bar.high / valley_bar.low - 1.0) * 100.0
    if growth < min_growth_pct(pump_class):
        return None
    vol_ratio = volume_ratio_median_24h_48h(state, now_ms)
    if vol_ratio is None:
        vol_ratio = volume_ratio_min_to_peak(
            bars_15,
            valley_bar.timestamp,
            peak_bar.timestamp,
            now_ms - lookback,
        )
    if not _volume_ok(
        pump_class,
        vol_ratio,
        relaxed=True,
        allow_missing_volume=False,
    ):
        return None
    if not _price_trend_ok(state, bars_15, now_ms):
        return None
    price = state.last_price or peak_bar.high
    if drawdown_from_peak_pct(price or 0, peak_bar.high) >= max_drawdown_pct():
        return None
    return EpisodeDraft(
        symbol=state.symbol,
        valley_price=valley_bar.low,
        valley_ts=valley_bar.timestamp,
        peak_price=peak_bar.high,
        peak_ts=peak_bar.timestamp,
        growth_pct=growth,
        pump_class=pump_class,
        volume_ratio=vol_ratio,
        source=source,
    )


def _class_from_duration(valley_ts: int, peak_ts: int) -> str:
    return pump_class_from_duration(max(0, peak_ts - valley_ts))


def _volume_ok(
    pump_class: str,
    vol_ratio: float | None,
    *,
    relaxed: bool,
    allow_missing_volume: bool = False,
) -> bool:
    need = min_volume_ratio(pump_class)
    if vol_ratio is not None and vol_ratio >= need:
        return True
    if relaxed and vol_ratio is not None and vol_ratio >= config.PUMP_UNIFIED_VOLUME_RELAXED:
        return True
    if allow_missing_volume and vol_ratio is None:
        return True
    if config.PUMP_UNIFIED_ALLOW_WITHOUT_VOLUME:
        return True
    return False


def _draft_from_min_max(
    state: SymbolState,
    now_ms: int,
    pump_class: str,
    valley_bar: Bar,
    peak_bar: Bar,
    *,
    source: str,
    relaxed_volume: bool,
    allow_missing_volume: bool = False,
) -> EpisodeDraft | None:
    peak = peak_bar.high
    valley = valley_bar.low
    if peak <= 0 or valley <= 0 or peak_bar.timestamp <= valley_bar.timestamp:
        return None
    growth = (peak / valley - 1.0) * 100.0
    if growth < min_growth_pct(pump_class):
        return None
    bars = merged_15m(state)
    window_start = now_ms - window_ms(pump_class)
    vol_ratio = volume_ratio_min_to_peak(bars, valley_bar.timestamp, peak_bar.timestamp, window_start)
    if not _volume_ok(
        pump_class,
        vol_ratio,
        relaxed=relaxed_volume,
        allow_missing_volume=allow_missing_volume,
    ):
        return None
    price = state.last_price or (bars[-1].close if bars else peak)
    if drawdown_from_peak_pct(price or 0, peak) >= max_drawdown_pct():
        return None
    return EpisodeDraft(
        symbol=state.symbol,
        valley_price=valley,
        valley_ts=valley_bar.timestamp,
        peak_price=peak,
        peak_ts=peak_bar.timestamp,
        growth_pct=growth,
        pump_class=pump_class,
        volume_ratio=vol_ratio,
        source=source,
    )


def _drafts_15m_windows(state: SymbolState, now_ms: int) -> list[EpisodeDraft]:
    bars = merged_15m(state)
    if len(bars) < 8:
        return []
    out: list[EpisodeDraft] = []
    for pump_class in ("fast", "medium", "long"):
        win = window_ms(pump_class)
        recent = [b for b in bars if b.timestamp >= now_ms - win and b.timestamp <= now_ms]
        if len(recent) < 4:
            continue
        valley_bar = min(recent, key=lambda b: b.low)
        after = [b for b in recent if b.timestamp >= valley_bar.timestamp]
        if len(after) < 2:
            continue
        peak_bar = max(after, key=lambda b: b.high)
        draft = _draft_from_min_max(
            state,
            now_ms,
            pump_class,
            valley_bar,
            peak_bar,
            source="bars_15m",
            relaxed_volume=False,
        )
        if draft is not None:
            out.append(draft)
    return out


def _draft_24h_ticker(state: SymbolState, now_ms: int) -> EpisodeDraft | None:
    pct = price_24h_pct(state.price_24h_change)
    if pct is None or pct < config.PUMP_UNIFIED_MIN_24H_PCT:
        return None
    bars = merged_15m(state)
    window = [b for b in bars if b.timestamp >= now_ms - DAY_MS]
    if len(window) < 4:
        return None
    valley_bar = min(window, key=lambda b: b.low)
    after = [b for b in window if b.timestamp >= valley_bar.timestamp]
    if len(after) < 2:
        return None
    peak_bar = max(after, key=lambda b: b.high)
    pump_class = _class_from_duration(valley_bar.timestamp, peak_bar.timestamp)
    if pump_class == "fast" and pct >= config.PUMP_UNIFIED_GROWTH_MIN_MEDIUM:
        pump_class = "medium"
    growth_bars = (peak_bar.high / valley_bar.low - 1.0) * 100.0
    if growth_bars < config.PUMP_UNIFIED_MIN_24H_PCT:
        return None
    pump_class = "medium"
    bars = merged_15m(state)
    vol_ratio = volume_ratio_min_to_peak(bars, valley_bar.timestamp, peak_bar.timestamp, now_ms - DAY_MS)
    price = state.last_price or peak_bar.high
    if drawdown_from_peak_pct(price or 0, peak_bar.high) >= max_drawdown_pct():
        return None
    return EpisodeDraft(
        symbol=state.symbol,
        valley_price=valley_bar.low,
        valley_ts=valley_bar.timestamp,
        peak_price=peak_bar.high,
        peak_ts=peak_bar.timestamp,
        growth_pct=growth_bars,
        pump_class=pump_class,
        volume_ratio=vol_ratio,
        source="ticker_24h",
    )


def _draft_from_strategy(state: SymbolState, now_ms: int) -> EpisodeDraft | None:
    from signal_engine.pump_strategy import detect_best_pump

    match = detect_best_pump(state, now_ms)
    if match is None:
        return None
    pump_class = "fast" if match.kind == "short" else "long"
    duration = match.peak_ts - match.valley_ts
    if match.kind == "short":
        pump_class = _class_from_duration(match.valley_ts, match.peak_ts)
    elif duration <= config.PUMP_UNIFIED_MEDIUM_MAX_MS:
        pump_class = "medium"
    bars = merged_15m(state)
    window_start = now_ms - window_ms(pump_class)
    vol_ratio = volume_ratio_min_to_peak(bars, match.valley_ts, match.peak_ts, window_start)
    growth = match.growth_pct
    min_g = min_growth_pct(pump_class)
    if growth < min_g:
        if match.kind == "long" and growth >= (config.PUMP_UNIFIED_MIN_MULTIPLIER - 1.0) * 100.0:
            pump_class = "long"
            min_g = (config.PUMP_UNIFIED_MIN_MULTIPLIER - 1.0) * 100.0
        if growth < min_g:
            return None
    if not _volume_ok(pump_class, vol_ratio, relaxed=True):
        return None
    price = state.last_price or match.peak_price
    if drawdown_from_peak_pct(price or 0, match.peak_price) >= max_drawdown_pct():
        return None
    return EpisodeDraft(
        symbol=state.symbol,
        valley_price=match.valley_price,
        valley_ts=match.valley_ts,
        peak_price=match.peak_price,
        peak_ts=match.peak_ts,
        growth_pct=growth,
        pump_class=pump_class,
        volume_ratio=vol_ratio,
        source="pump_strategy",
    )


def _draft_from_history(state: SymbolState, now_ms: int) -> EpisodeDraft | None:
    hist = history_pump_metrics(state, now_ms)
    if hist is None or hist.peak_mult < config.PUMP_UNIFIED_MIN_MULTIPLIER:
        return None
    growth = (hist.peak_mult - 1.0) * 100.0
    pump_class = "long"
    interval = hist.interval
    bars = state.bars_htf.get(interval) or []
    window = [b for b in bars if b.timestamp >= hist.valley_ts]
    if len(window) < 2:
        window = bars[-10:]
    valley_bar = min(window, key=lambda b: b.low) if window else None
    peak_bar = max(window, key=lambda b: b.high) if window else None
    if valley_bar is None or peak_bar is None:
        return None
    bars_15 = merged_15m(state)
    window_start = now_ms - window_ms("long")
    vol_ratio = volume_ratio_min_to_peak(bars_15, valley_bar.timestamp, peak_bar.timestamp, window_start)
    if growth < min_growth_pct("long") and hist.peak_mult >= config.PUMP_UNIFIED_MIN_MULTIPLIER:
        pass
    elif growth < min_growth_pct("long"):
        return None
    if not _volume_ok("long", vol_ratio, relaxed=True):
        return None
    price = state.last_price or hist.peak_high
    if drawdown_from_peak_pct(price or 0, hist.peak_high) >= max_drawdown_pct():
        return None
    return EpisodeDraft(
        symbol=state.symbol,
        valley_price=hist.min_low,
        valley_ts=hist.valley_ts,
        peak_price=hist.peak_high,
        peak_ts=peak_bar.timestamp,
        growth_pct=max(growth, (hist.peak_high / hist.min_low - 1.0) * 100.0),
        pump_class=pump_class,
        volume_ratio=vol_ratio,
        source="history_htf",
    )


def _dedupe(drafts: list[EpisodeDraft]) -> list[EpisodeDraft]:
    best: dict[tuple[str, str], EpisodeDraft] = {}
    for d in drafts:
        key = (d.symbol, d.pump_class)
        prev = best.get(key)
        if prev is None or d.growth_pct > prev.growth_pct:
            best[key] = d
    return list(best.values())


def detect_unified_episodes(state: SymbolState, now_ms: int) -> list[EpisodeDraft]:
    """Все эпизоды пампа по единым правилам (объединение путей детекта)."""
    if not meets_unified_turnover(state):
        return []
    collected: list[EpisodeDraft] = []
    d7 = _draft_valley_lookback(state, now_ms)
    if d7 is not None:
        collected.append(d7)
    collected.extend(_drafts_15m_windows(state, now_ms))
    d24 = _draft_24h_ticker(state, now_ms)
    if d24 is not None:
        collected.append(d24)
    ds = _draft_from_strategy(state, now_ms)
    if ds is not None:
        collected.append(ds)
    dh = _draft_from_history(state, now_ms)
    if dh is not None:
        collected.append(dh)
    return _dedupe(collected)


def detect_unified_episode(state: SymbolState, now_ms: int) -> EpisodeDraft | None:
    drafts = detect_unified_episodes(state, now_ms)
    if not drafts:
        return None
    return max(drafts, key=lambda d: d.growth_pct)


def symbol_has_unified_pump(state: SymbolState, now_ms: int) -> bool:
    return bool(detect_unified_episodes(state, now_ms))
