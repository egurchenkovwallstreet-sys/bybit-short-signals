"""Памп и условия входа в виртуальный шорт. Чистые функции без SQLite и Redis.

Обязательные условия (все сразу): качество пампа (объём ×10, покупки ≥70%),
торможение в диапазоне, покупки упали, продажи перевешивают, объём падает
(или держится при снижении цены), ликвидации шортов затихли, OI за 1 ч < 0,
а при сильном росте BTC ещё пробой EMA50 15m или двойная вершина.
Остальное только добавляет баллы силы.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import config
from signal_engine.flow import oi_change_pct
from signal_engine.indicators import ema
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars, pivot_highs_indexed

MIN_MS = 60_000
HOUR_MS = 3_600_000
BAR_MS = {"1": MIN_MS, "15": 15 * MIN_MS, "30": 30 * MIN_MS, "60": HOUR_MS, "240": 4 * HOUR_MS}

MANDATORY = (
    "pump_volume",
    "pump_buys",
    "stall",
    "buys_faded",
    "sells_dominate",
    "volume_fade",
    "short_liq_faded",
    "oi_1h_negative",
    "btc_guard",
)

CHECK_LABELS = {
    "pump_volume": "Объём на росте ×10+",
    "pump_buys": "Агрессивные покупки на росте ≥70%",
    "stall": "Торможение: без нового хая, диапазон 5–10%",
    "buys_faded": "Агрессивные покупки упали",
    "sells_dominate": "Перевес агрессивных продаж 5/10/15 мин",
    "volume_fade": "Объём падает (или раздача)",
    "short_liq_faded": "Ликвидации шортов затихли ≥80%",
    "oi_1h_negative": "OI за 1 ч отрицательный",
    "btc_guard": "BTC: строгий режим пройден",
}

_TF_WEIGHT = {"15": 1.0, "30": 1.5, "60": 2.0, "240": 3.0}
_PERIOD_WEIGHT = {50: 1.0, 100: 1.25, 200: 1.5}
_TF_LABEL = {"15": "15m", "30": "30m", "60": "1H", "240": "4H"}


@dataclass
class PumpInfo:
    kind: str
    trigger: str
    growth_pct: float
    valley_price: float
    valley_ts: int
    peak_price: float
    peak_ts: int
    growth: dict[str, float | None] = field(default_factory=dict)
    volume_ratio: float | None = None
    volume_avg_ratio: float | None = None
    buy_share_pct: float | None = None
    tape_minutes: int = 0

    @property
    def duration_ms(self) -> int:
        return max(0, self.peak_ts - self.valley_ts)

    def to_data(self) -> dict:
        return {
            "kind": self.kind,
            "kind_label": "Короткий" if self.kind == "short" else "Длинный",
            "trigger": self.trigger,
            "growth_pct": _r(self.growth_pct, 2),
            "valley_price": self.valley_price,
            "valley_ts": self.valley_ts,
            "peak_price": self.peak_price,
            "peak_ts": self.peak_ts,
            "duration_min": round(self.duration_ms / MIN_MS),
            "growth": {k: _r(v, 2) for k, v in self.growth.items()},
            "volume_ratio": _r(self.volume_ratio, 2),
            "volume_avg_ratio": _r(self.volume_avg_ratio, 2),
            "buy_share_pct": _r(self.buy_share_pct, 1),
            "tape_minutes": self.tape_minutes,
        }


@dataclass
class Evaluation:
    checks: dict[str, dict]
    metrics: dict
    score: float
    score_parts: dict[str, float]
    strict_btc: bool

    @property
    def passed(self) -> bool:
        return all(self.checks[key]["ok"] for key in MANDATORY)

    @property
    def failed(self) -> list[str]:
        return [key for key in MANDATORY if not self.checks[key]["ok"]]

    def to_data(self) -> dict:
        return {
            "checks": self.checks,
            "metrics": self.metrics,
            "score": round(self.score, 1),
            "grade": grade_for(self.score),
            "score_parts": {k: round(v, 2) for k, v in self.score_parts.items() if v},
            "strict_btc": self.strict_btc,
            "passed": self.passed,
            "failed": self.failed,
        }


def grade_for(score: float) -> str:
    if score >= 40:
        return "A"
    if score >= 20:
        return "B"
    return "C"


# --- ряды свечей -------------------------------------------------------------


def merged_15m(state: SymbolState) -> list[Bar]:
    """15m из REST, где есть минутки — пересобранные из них (свежее REST-круга)."""
    by_ts = {bar.timestamp: Bar(bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume)
             for bar in state.bars_htf.get("15", [])}
    minutes = state.bars_1m
    if minutes:
        step = BAR_MS["15"]
        first = minutes[0].timestamp
        groups: dict[int, list[Bar]] = {}
        for bar in minutes:
            key = (bar.timestamp // step) * step
            if key < first and key in by_ts:
                continue
            groups.setdefault(key, []).append(bar)
        for key, rows in groups.items():
            by_ts[key] = Bar(
                key,
                rows[0].open,
                max(r.high for r in rows),
                min(r.low for r in rows),
                rows[-1].close,
                sum(r.volume for r in rows),
            )
    return [by_ts[k] for k in sorted(by_ts)]


def live_4h(state: SymbolState) -> list[Bar]:
    bars = [Bar(b.timestamp, b.open, b.high, b.low, b.close, b.volume) for b in state.bars_htf.get("240", [])]
    if not bars or not state.bars_1m:
        return bars
    last = bars[-1]
    tail = [b for b in state.bars_1m if b.timestamp >= last.timestamp]
    if tail:
        last.high = max(last.high, max(b.high for b in tail))
        last.low = min(last.low, min(b.low for b in tail))
        last.close = tail[-1].close
    return bars


# --- памп --------------------------------------------------------------------


def _valley(bars: list[Bar], peak_ts: int, window_ms: int) -> Bar | None:
    rows = [b for b in bars if peak_ts - window_ms <= b.timestamp <= peak_ts]
    if not rows:
        return None
    return min(rows, key=lambda b: b.low)


def _growth(peak: float, valley: Bar | None) -> float | None:
    if valley is None or valley.low <= 0:
        return None
    return (peak / valley.low - 1.0) * 100.0


def _precise_peak_ts(state: SymbolState, bucket_ts: int, peak_price: float) -> int:
    best = None
    for bar in state.bars_1m:
        if bucket_ts <= bar.timestamp < bucket_ts + BAR_MS["15"] and bar.high >= peak_price * 0.9999:
            best = bar.timestamp if best is None else best
    return best if best is not None else bucket_ts


def find_pump(state: SymbolState, tape: SymbolTape | None, now_ms: int) -> PumpInfo | None:
    """Пик за время жизни кандидата и рост к нему из окон 4 ч / 24 ч / 7 д / 14 д."""
    bars15 = merged_15m(state)
    if len(bars15) < 8:
        return None
    lifetime = max(config.PAPER_SHORT_LIFETIME_HOURS, config.PAPER_LONG_LIFETIME_HOURS) * HOUR_MS
    recent = [b for b in bars15 if b.timestamp >= now_ms - lifetime]
    if not recent:
        return None
    peak_bar = max(recent, key=lambda b: b.high)
    peak = peak_bar.high
    if peak <= 0:
        return None
    peak_ts = _precise_peak_ts(state, peak_bar.timestamp, peak)
    last = state.last_price or bars15[-1].close
    if last <= 0 or (1 - last / peak) * 100.0 > config.PAPER_MAX_DRAWDOWN_FROM_PEAK_PCT:
        return None

    bars4h = live_4h(state)
    v4h = _valley(bars15, peak_ts, 4 * HOUR_MS)
    v24 = _valley(bars15, peak_ts, 24 * HOUR_MS)
    v7d = _valley(bars4h, peak_ts, 7 * 24 * HOUR_MS)
    v14 = _valley(bars4h, peak_ts, 14 * 24 * HOUR_MS)
    growth = {"4h": _growth(peak, v4h), "24h": _growth(peak, v24), "7d": _growth(peak, v7d), "14d": _growth(peak, v14)}

    since_peak = now_ms - peak_ts
    choice: tuple[str, str, Bar, float] | None = None
    if since_peak <= config.PAPER_SHORT_LIFETIME_HOURS * HOUR_MS:
        if growth["4h"] is not None and growth["4h"] > config.PAPER_SHORT_4H_MIN_PCT:
            choice = ("short", "4h", v4h, growth["4h"])
        elif growth["24h"] is not None and growth["24h"] >= config.PAPER_SHORT_24H_MIN_PCT:
            choice = ("short", "24h", v24, growth["24h"])
    if choice is None and since_peak <= config.PAPER_LONG_LIFETIME_HOURS * HOUR_MS:
        if growth["7d"] is not None and growth["7d"] >= config.PAPER_LONG_7D_MIN_PCT:
            choice = ("long", "7d", v7d, growth["7d"])
        elif growth["14d"] is not None and growth["14d"] >= config.PAPER_LONG_14D_MIN_PCT:
            choice = ("long", "14d", v14, growth["14d"])
    if choice is None:
        return None
    kind, trigger, valley, pct = choice
    assert valley is not None
    info = PumpInfo(
        kind=kind,
        trigger=trigger,
        growth_pct=pct,
        valley_price=valley.low,
        valley_ts=valley.timestamp,
        peak_price=peak,
        peak_ts=peak_ts,
        growth=growth,
    )
    series = bars15 if kind == "short" else bars4h
    info.volume_ratio, info.volume_avg_ratio = leg_volume_ratio(series, valley.timestamp, peak_ts)
    if tape is not None:
        buy, sell, covered = tape.buy_sell_between(valley.timestamp, peak_ts)
        info.tape_minutes = covered
        need = min(config.PAPER_PUMP_TAPE_MIN_MINUTES, max(5, info.duration_ms // MIN_MS))
        if covered >= need and buy + sell > 0:
            info.buy_share_pct = buy / (buy + sell) * 100.0
    return info


def leg_volume_ratio(bars: list[Bar], valley_ts: int, peak_ts: int) -> tuple[float | None, float | None]:
    """Макс. и средний объём бара на ноге роста к средней N баров до начала роста."""
    if not bars:
        return None, None
    step = bars[1].timestamp - bars[0].timestamp if len(bars) > 1 else BAR_MS["15"]
    start = (valley_ts // step) * step
    leg = [b.volume for b in bars if start <= b.timestamp <= peak_ts]
    base = [b.volume for b in bars if b.timestamp < start][-config.PAPER_PUMP_VOLUME_BASE_BARS :]
    if not leg or len(base) < max(5, config.PAPER_PUMP_VOLUME_BASE_BARS // 2):
        return None, None
    mean = sum(base) / len(base)
    if mean <= 0:
        return None, None
    return max(leg) / mean, (sum(leg) / len(leg)) / mean


# --- индикаторы для силы сигнала ---------------------------------------------


def ema_table(klines: dict[str, list[Bar]], now_ms: int) -> dict[str, dict]:
    """Для каждой пары TF×период: значение EMA, закрытие последней свечи, пробита ли."""
    out: dict[str, dict] = {}
    for interval in config.PAPER_EMA_INTERVALS:
        bars = closed_bars(klines.get(interval) or [], interval, now_ms)
        closes = [b.close for b in bars]
        for period in config.PAPER_EMA_PERIODS:
            key = f"{_TF_LABEL[interval]}_EMA{period}"
            series = ema(closes, period) if closes else []
            value = series[-1] if series else None
            close = closes[-1] if closes else None
            out[key] = {
                "interval": interval,
                "period": period,
                "ema": value,
                "close": close,
                "broken": bool(value is not None and close is not None and close < value),
                "weight": _TF_WEIGHT[interval] * _PERIOD_WEIGHT[period],
            }
    return out


def double_top(bars: list[Bar], interval: str, min_between: int, now_ms: int) -> dict | None:
    closed = closed_bars(bars, interval, now_ms)
    if len(closed) < min_between + 6:
        return None
    pivots = pivot_highs_indexed(closed, config.PAPER_DT_PIVOT_WING)
    if len(pivots) < 2:
        return None
    second = pivots[-1]
    if now_ms - second["time"] < config.PAPER_DT_MIN_HOURS_AFTER * HOUR_MS:
        return None
    after = closed[second["bar_index"] + 1 :]
    best = None
    for first in reversed(pivots[:-1]):
        if second["bar_index"] - first["bar_index"] < min_between:
            continue
        top = max(first["price"], second["price"])
        diff = abs(first["price"] - second["price"]) / top * 100.0
        if diff > config.PAPER_DT_MAX_DIFF_PCT:
            continue
        between = closed[first["bar_index"] + 1 : second["bar_index"]]
        if between and max(b.high for b in between) > top:
            continue
        if after and max(b.high for b in after) > top:
            continue
        if best is None or diff < best["diff_pct"]:
            best = {
                "interval": interval,
                "first_price": first["price"],
                "first_ts": first["time"],
                "second_price": second["price"],
                "second_ts": second["time"],
                "bars_between": second["bar_index"] - first["bar_index"],
                "diff_pct": round(diff, 2),
                "hours_after": round((now_ms - second["time"]) / HOUR_MS, 1),
            }
    return best


def round_level_near(price: float) -> dict | None:
    """Ближайший крупный круглый уровень (шаг — половина порядка цены) и его вес."""
    if price <= 0:
        return None
    magnitude = 10.0 ** math.floor(math.log10(price))
    step = magnitude / 2.0
    candidates = [math.floor(price / step) * step, math.ceil(price / step) * step]
    level = min(candidates, key=lambda lv: abs(lv - price))
    if level <= 0:
        return None
    dist = abs(price - level) / level * 100.0
    if dist > config.PAPER_ROUND_LEVEL_NEAR_PCT:
        return None
    units = round(level / magnitude, 6)
    if abs(units - round(units)) < 1e-6 and int(round(units)) % 5 == 0:
        weight = 8.0
    elif abs(units - round(units)) < 1e-6:
        weight = 5.0
    else:
        weight = 3.0
    digits = max(0, -int(math.floor(math.log10(step))) + 1)
    return {"level": round(level, digits), "distance_pct": round(dist, 2), "weight": weight}


def btc_change_4h(btc: SymbolState | None, now_ms: int) -> float | None:
    if btc is None or not btc.last_price:
        return None
    bars = merged_15m(btc)
    target = now_ms - 4 * HOUR_MS
    ref = None
    for bar in bars:
        if bar.timestamp <= target:
            ref = bar.close
        else:
            break
    if ref is None or ref <= 0:
        return None
    return (btc.last_price / ref - 1.0) * 100.0


# --- условия входа -----------------------------------------------------------


def _check(ok: bool, value, need: str) -> dict:
    return {"ok": bool(ok), "value": value, "need": need}


def evaluate(
    state: SymbolState,
    tape: SymbolTape,
    pump: PumpInfo,
    klines: dict[str, list[Bar]],
    btc_4h_pct: float | None,
    now_ms: int,
) -> Evaluation:
    checks: dict[str, dict] = {}
    metrics: dict = {"pump": pump.to_data()}
    last = float(state.last_price or pump.peak_price)
    metrics["last_price"] = last
    metrics["drawdown_from_peak_pct"] = _r((1 - last / pump.peak_price) * 100.0, 2)

    vr = pump.volume_ratio
    checks["pump_volume"] = _check(
        vr is not None and vr >= config.PAPER_PUMP_VOLUME_MIN_RATIO,
        _r(vr, 2),
        f"≥ ×{config.PAPER_PUMP_VOLUME_MIN_RATIO:g}",
    )
    bs = pump.buy_share_pct
    checks["pump_buys"] = _check(
        bs is not None and bs >= config.PAPER_PUMP_BUY_SHARE_MIN_PCT,
        _r(bs, 1) if bs is not None else f"нет ленты ({pump.tape_minutes} мин)",
        f"≥ {config.PAPER_PUMP_BUY_SHARE_MIN_PCT:g}%",
    )

    # Торможение: время с пика и ширина диапазона за последние ≤2 ч.
    since_peak_min = (now_ms - pump.peak_ts) / MIN_MS
    window_min = min(since_peak_min, config.PAPER_STALL_MAX_MINUTES)
    window_bars = [b for b in state.bars_1m if b.timestamp >= now_ms - window_min * MIN_MS]
    width = None
    if window_bars:
        hi = max(b.high for b in window_bars)
        lo = min(b.low for b in window_bars)
        width = (hi - lo) / hi * 100.0 if hi > 0 else None
    stall_ok = (
        since_peak_min >= config.PAPER_STALL_MIN_MINUTES
        and width is not None
        and config.PAPER_RANGE_MIN_PCT <= width <= config.PAPER_RANGE_MAX_PCT
    )
    checks["stall"] = _check(
        stall_ok,
        {"since_peak_min": round(since_peak_min), "range_pct": _r(width, 2), "window_min": round(window_min)},
        f"≥ {config.PAPER_STALL_MIN_MINUTES} мин без хая, диапазон {config.PAPER_RANGE_MIN_PCT:g}–{config.PAPER_RANGE_MAX_PCT:g}%",
    )

    cur_buy, _ = tape.minute_window(now_ms, 15)
    peak_buy = tape.peak_buy_window(now_ms, 15)
    buy_ratio = cur_buy / peak_buy if peak_buy > 0 else None
    checks["buys_faded"] = _check(
        buy_ratio is not None and buy_ratio <= config.PAPER_BUYS_FADE_MAX_RATIO,
        {"ratio": _r(buy_ratio, 2), "last15_usd": round(cur_buy), "peak15_usd": round(peak_buy)},
        f"покупки 15 мин ≤ {config.PAPER_BUYS_FADE_MAX_RATIO * 100:g}% от пика",
    )

    sell_shares: dict[str, float | None] = {}
    winners = 0
    for minutes in config.PAPER_SELL_WINDOWS_MIN:
        b, s = tape.minute_window(now_ms, minutes)
        share = s / (b + s) * 100.0 if b + s > 0 else None
        sell_shares[f"{minutes}m"] = _r(share, 1)
        if share is not None and share > config.PAPER_SELL_SHARE_MIN_PCT:
            winners += 1
    checks["sells_dominate"] = _check(
        winners >= config.PAPER_SELL_WINDOWS_REQUIRED,
        sell_shares,
        f"продажи > {config.PAPER_SELL_SHARE_MIN_PCT:g}% хотя бы в {config.PAPER_SELL_WINDOWS_REQUIRED} окнах из 3",
    )

    vol_ratio, price_20m = _volume_and_price(state)
    fading = vol_ratio is not None and vol_ratio <= config.PAPER_VOLUME_FADE_MAX_RATIO
    distribution = (
        not fading
        and vol_ratio is not None
        and price_20m is not None
        and price_20m <= -config.PAPER_DISTRIBUTION_PRICE_DROP_PCT
    )
    checks["volume_fade"] = _check(
        fading or distribution,
        {"ratio": _r(vol_ratio, 2), "price_20m_pct": _r(price_20m, 2), "mode": "раздача" if distribution else ("спад" if fading else "—")},
        f"объём 20 мин ≤ {config.PAPER_VOLUME_FADE_MAX_RATIO * 100:g}% пика или цена −{config.PAPER_DISTRIBUTION_PRICE_DROP_PCT:g}% при объёме",
    )

    short_liq = tape.liq_series(now_ms, config.PAPER_SHORT_LIQ_WINDOW_MIN, "short")
    liq_peak = max(short_liq) if short_liq else 0.0
    liq_now = max(short_liq[-2:]) if short_liq else 0.0
    fade = 1.0 if liq_peak <= 0 else 1.0 - liq_now / liq_peak
    checks["short_liq_faded"] = _check(
        fade >= config.PAPER_SHORT_LIQ_FADE_MIN,
        {"fade_pct": round(fade * 100), "peak_usd": round(liq_peak), "now_usd": round(liq_now)},
        f"поток упал ≥ {config.PAPER_SHORT_LIQ_FADE_MIN * 100:g}% от пика за {config.PAPER_SHORT_LIQ_WINDOW_MIN} мин",
    )

    points = state.oi_points()
    oi_1h = oi_change_pct(points, lookback_min=60) if len(points) >= 2 else None
    oi_4h = oi_change_pct(points, lookback_min=240) if len(points) >= 2 else None
    checks["oi_1h_negative"] = _check(oi_1h is not None and oi_1h < 0, _r(oi_1h, 2), "< 0%")

    emas = ema_table(klines, now_ms)
    dt_1h = double_top(klines.get("60") or [], "60", config.PAPER_DT_MIN_BARS_1H, now_ms)
    dt_30 = double_top(klines.get("30") or [], "30", config.PAPER_DT_MIN_BARS_30M, now_ms)
    dtop = dt_1h or dt_30
    strict = btc_4h_pct is not None and btc_4h_pct >= config.PAPER_BTC_STRICT_4H_PCT
    ema15_50 = emas.get("15m_EMA50", {}).get("broken", False)
    checks["btc_guard"] = _check(
        (not strict) or ema15_50 or dtop is not None,
        {"btc_4h_pct": _r(btc_4h_pct, 2), "strict": strict, "ema15_50_broken": ema15_50, "double_top": dtop is not None},
        f"при BTC ≥ +{config.PAPER_BTC_STRICT_4H_PCT:g}% за 4 ч — пробой EMA50 15m или двойная вершина",
    )

    long_liq = sum(tape.liq_series(now_ms, 15, "long"))
    short_liq_15 = sum(short_liq)
    funding = state.funding_rate
    level = round_level_near(pump.peak_price)

    parts: dict[str, float] = {}
    ema_max = sum(_TF_WEIGHT.values()) * sum(_PERIOD_WEIGHT.values())
    ema_sum = sum(row["weight"] for row in emas.values() if row["broken"])
    parts["ema"] = ema_sum / ema_max * 40.0
    parts["double_top"] = 10.0 if dtop else 0.0
    parts["round_level"] = level["weight"] if level else 0.0
    if long_liq > 0:
        parts["long_liq"] = 5.0 if long_liq >= short_liq_15 else 2.0
    if oi_1h is not None and oi_1h < 0:
        parts["oi_1h"] = min(abs(oi_1h), 10.0)
    if oi_4h is not None and oi_4h < 0:
        parts["oi_4h"] = min(abs(oi_4h), 15.0) * 0.5
    if funding is not None and funding > 0:
        parts["funding"] = min(funding * 10_000.0, 10.0)
    if btc_4h_pct is not None and btc_4h_pct < 0:
        parts["btc_down"] = min(abs(btc_4h_pct), 5.0) * 2.0
    if liq_peak > 0 and fade >= config.PAPER_SHORT_LIQ_FADE_STRONG:
        parts["short_liq_90"] = 3.0
    if distribution:
        parts["distribution"] = 5.0
    score = sum(parts.values())

    metrics.update(
        {
            "since_peak_min": round(since_peak_min),
            "range_pct": _r(width, 2),
            "buys_15m_usd": round(cur_buy),
            "buys_peak15_usd": round(peak_buy),
            "buys_fade_ratio": _r(buy_ratio, 2),
            "sell_share": sell_shares,
            "volume_ratio_20m": _r(vol_ratio, 2),
            "price_20m_pct": _r(price_20m, 2),
            "distribution": distribution,
            "short_liq_15m_usd": round(short_liq_15),
            "short_liq_fade_pct": round(fade * 100),
            "long_liq_15m_usd": round(long_liq),
            "oi_1h_pct": _r(oi_1h, 2),
            "oi_4h_pct": _r(oi_4h, 2),
            "funding_rate": funding,
            "btc_4h_pct": _r(btc_4h_pct, 2),
            "turnover_24h_usd": state.turnover_24h_usdt,
            "ema": {k: {"ema": v["ema"], "close": v["close"], "broken": v["broken"]} for k, v in emas.items()},
            "ema_broken": [k for k, v in emas.items() if v["broken"]],
            "double_top": dtop,
            "round_level": level,
        }
    )
    return Evaluation(checks=checks, metrics=metrics, score=score, score_parts=parts, strict_btc=strict)


def _volume_and_price(state: SymbolState) -> tuple[float | None, float | None]:
    bars = state.bars_1m[:-1]
    window = config.PAPER_VOLUME_WINDOW_MIN
    if len(bars) < window * 2:
        return None, None
    volumes = [b.volume for b in bars]
    recent = sum(volumes[-window:]) / window
    best = 0.0
    running = sum(volumes[:window])
    best = running
    for i in range(window, len(volumes)):
        running += volumes[i] - volumes[i - window]
        best = max(best, running)
    peak = best / window
    ratio = recent / peak if peak > 0 else None
    ref = bars[-window].close
    last = state.last_price or bars[-1].close
    price = (last / ref - 1.0) * 100.0 if ref > 0 else None
    return ratio, price


def _r(value, digits: int):
    if value is None:
        return None
    try:
        if math.isnan(value) or math.isinf(value):
            return None
    except TypeError:
        return value
    return round(float(value), digits)
