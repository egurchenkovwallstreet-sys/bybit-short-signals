"""Курсор СС 2: шорт быстрого пампа после подтверждённого разворота.

Вход только в окне отката 5–8% от пика, когда лента, OI часа, BTC и стакан
уже развернулись. Один вход на долину. Стоп и цели — в position/strategy.
"""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.flow import oi_change_pct
from signal_engine.paper.detect import (
    HOUR_MS,
    MIN_MS,
    _check,
    _r,
    grade_for,
    leg_volume_ratio,
    merged_15m,
    strong_top,
)
from signal_engine.paper.tape import SymbolTape, minute_start
from signal_engine.state import Bar, SymbolState


CSS2_MANDATORY = (
    "turnover",
    "since_peak",
    "drawdown_band",
    "not_late_megavol",
    "not_late_double_top",
    "peak_not_forming",
    "sells_dominate",
    "buy_share_5m",
    "price_15m_down",
    "short_liq_faded",
    "oi_1h_flat",
    "not_beating_btc",
    "book_asks",
)

CSS2_CHECK_LABELS = {
    "turnover": "Оборот 24ч ≥ $1 млн",
    "since_peak": "С пика 20–180 мин",
    "drawdown_band": "Откат от пика 5–8%",
    "not_late_megavol": "Не мегаобъём после 60 мин",
    "not_late_double_top": "Не двойная вершина после 60 мин",
    "peak_not_forming": "Пик не на открытой 15м",
    "sells_dominate": "Продажи > 50% в 2 окнах из 5/10/15",
    "buy_share_5m": "Покупки 5 мин ≤ 45%",
    "price_15m_down": "Цена за 15 мин ≤ 0",
    "short_liq_faded": "Ликвидации шортов ≤ 15% пика",
    "oi_1h_flat": "OI за 1 ч ≤ +1%",
    "not_beating_btc": "Монета не обгоняет BTC за 15 мин",
    "book_asks": "В ±1% стакана асков не меньше бидов",
}


@dataclass
class Css2PumpInfo:
    valley_price: float
    valley_ts: int
    peak_price: float
    peak_ts: int
    growth_pct: float
    volume_ratio: float | None = None

    @property
    def duration_ms(self) -> int:
        return max(0, self.peak_ts - self.valley_ts)

    def to_data(self) -> dict:
        return {
            "kind": "css2",
            "trigger": "css2",
            "growth_pct": _r(self.growth_pct, 2),
            "valley_price": self.valley_price,
            "valley_ts": self.valley_ts,
            "peak_price": self.peak_price,
            "peak_ts": self.peak_ts,
            "duration_min": round(self.duration_ms / MIN_MS),
            "volume_ratio": _r(self.volume_ratio, 2),
        }


@dataclass
class Css2Evaluation:
    checks: dict[str, dict]
    metrics: dict
    score: float

    @property
    def passed(self) -> bool:
        return all(self.checks[k]["ok"] for k in CSS2_MANDATORY)

    @property
    def failed(self) -> list[str]:
        return [k for k in CSS2_MANDATORY if not self.checks[k]["ok"]]

    @property
    def passed_count(self) -> int:
        return len(CSS2_MANDATORY) - len(self.failed)

    def to_data(self) -> dict:
        return {
            "checks": self.checks,
            "metrics": self.metrics,
            "score": round(self.score, 1),
            "grade": grade_for(self.score),
            "strict_btc": False,
            "passed": self.passed,
            "passed_count": self.passed_count,
            "failed": self.failed,
            "variants": [config.PAPER_CSS2_VARIANT] if self.passed else [],
            "entry_blocked": [],
        }


def _precise_peak_ts(state: SymbolState, bucket_ts: int, peak_price: float) -> int:
    hits = [
        b
        for b in state.bars_1m
        if bucket_ts <= b.timestamp < bucket_ts + 15 * MIN_MS and b.high >= peak_price * 0.9999
    ]
    if not hits:
        return bucket_ts
    return max(hits, key=lambda b: (b.high, b.timestamp)).timestamp


def find_css2_pump(state: SymbolState, now_ms: int) -> Css2PumpInfo | None:
    """Быстрый памп: +40% за ≤6 ч. Окно входа проверяет evaluate, не поиск."""
    bars15 = merged_15m(state)
    if len(bars15) < 8:
        return None
    last = float(state.last_price or 0)
    if last <= 0:
        return None
    lookback = now_ms - int(config.PAPER_CSS2_LOOKBACK_HOURS * HOUR_MS)
    recent = [b for b in bars15 if b.timestamp >= lookback]
    if not recent:
        return None
    peak_bar = max(recent, key=lambda b: b.high)
    peak = peak_bar.high
    if peak <= 0:
        return None
    peak_ts = _precise_peak_ts(state, peak_bar.timestamp, peak)
    if last > peak:
        peak = last
        peak_ts = now_ms
    dd = (1.0 - last / peak) * 100.0
    if dd > config.PAPER_CSS2_WATCH_MAX_DD_PCT:
        return None
    if now_ms - peak_ts > int(config.PAPER_CSS2_SINCE_PEAK_MAX * MIN_MS):
        return None
    leg_ms = int(config.PAPER_CSS2_MAX_LEG_HOURS * HOUR_MS)
    window = [b for b in bars15 if peak_ts - leg_ms <= b.timestamp <= peak_ts]
    if not window:
        return None
    valley = min(window, key=lambda b: b.low)
    if valley.low <= 0:
        return None
    growth = (peak / valley.low - 1.0) * 100.0
    if growth < config.PAPER_CSS2_MIN_GROWTH_PCT:
        return None
    duration = peak_ts - valley.timestamp
    if duration <= 0 or duration > leg_ms:
        return None
    info = Css2PumpInfo(
        valley_price=valley.low,
        valley_ts=valley.timestamp,
        peak_price=peak,
        peak_ts=peak_ts,
        growth_pct=growth,
    )
    info.volume_ratio, _ = leg_volume_ratio(bars15, valley.timestamp, peak_ts)
    return info


def price_change_pct(state: SymbolState, now_ms: int, minutes: int) -> float | None:
    if not state.last_price:
        return None
    target = now_ms - minutes * MIN_MS
    ref = None
    for bar in state.bars_1m:
        if bar.timestamp <= target and bar.close > 0:
            ref = bar.close
        elif bar.timestamp > target:
            break
    if ref is None or ref <= 0:
        return None
    return (float(state.last_price) / ref - 1.0) * 100.0


def book_imbalance_1pct(state: SymbolState) -> float | None:
    """(bid − ask) / (bid + ask) в полосе ±1% от цены. Объём в USD."""
    last = float(state.last_price or 0)
    if last <= 0:
        return None
    lo, hi = last * 0.99, last * 1.01
    bid = sum(px * sz for px, sz in state.book_bids.items() if lo <= px <= last and sz > 0)
    ask = sum(px * sz for px, sz in state.book_asks.items() if last <= px <= hi and sz > 0)
    if bid + ask <= 0:
        return None
    return (bid - ask) / (bid + ask)


def short_liq_15m(tape: SymbolTape, peak_ts: int, now_ms: int) -> tuple[float, float]:
    """Текущие ликвидации шортов за 15 мин и максимум такого окна с пика."""
    current = minute_start(now_ms)
    start = minute_start(peak_ts)
    if start > current:
        start = current
    series: list[float] = []
    cursor = start
    while cursor <= current:
        series.append(float(tape.liq_short.get(cursor, 0.0)))
        cursor += MIN_MS
    if not series:
        return 0.0, 0.0
    width = 15
    if len(series) <= width:
        total = sum(series)
        return total, total
    running = sum(series[:width])
    best = running
    for i in range(width, len(series)):
        running += series[i] - series[i - width]
        if running > best:
            best = running
    return sum(series[-width:]), best


def peak_on_open_15m(state: SymbolState, peak: float, now_ms: int) -> bool:
    bars = merged_15m(state)
    if not bars or peak <= 0:
        return False
    last = bars[-1]
    if now_ms >= last.timestamp + 15 * MIN_MS:
        return False
    return last.high >= peak * 0.999


def closed_15m_above_peak(state: SymbolState, peak: float, opened_at: int, now_ms: int) -> bool:
    bars = merged_15m(state)
    if not bars or peak <= 0:
        return False
    for bar in bars:
        closed_at = bar.timestamp + 15 * MIN_MS
        if closed_at < opened_at or closed_at > now_ms:
            continue
        if bar.close > peak * 1.0001:
            return True
    return False


def evaluate_css2(
    state: SymbolState,
    tape: SymbolTape | None,
    btc: SymbolState | None,
    pump: Css2PumpInfo,
    klines: dict[str, list[Bar]],
    now_ms: int,
) -> Css2Evaluation:
    checks: dict[str, dict] = {}
    last = float(state.last_price or pump.peak_price)
    dd = (1.0 - last / pump.peak_price) * 100.0 if pump.peak_price > 0 else None
    since = (now_ms - pump.peak_ts) / MIN_MS
    metrics: dict = {
        "pump": pump.to_data(),
        "last_price": last,
        "drawdown_from_peak_pct": _r(dd, 2),
        "since_peak_min": round(since),
    }

    turnover = state.turnover_24h_usdt
    checks["turnover"] = _check(
        turnover is not None and turnover >= config.PAPER_CSS2_MIN_TURNOVER_USDT,
        _r(turnover, 0),
        "≥ 1 000 000 USDT",
    )
    checks["since_peak"] = _check(
        config.PAPER_CSS2_SINCE_PEAK_MIN <= since <= config.PAPER_CSS2_SINCE_PEAK_MAX,
        round(since),
        f"{config.PAPER_CSS2_SINCE_PEAK_MIN:g}–{config.PAPER_CSS2_SINCE_PEAK_MAX:g} мин",
    )
    checks["drawdown_band"] = _check(
        dd is not None and config.PAPER_CSS2_DD_MIN_PCT <= dd <= config.PAPER_CSS2_DD_MAX_PCT,
        _r(dd, 2),
        f"{config.PAPER_CSS2_DD_MIN_PCT:g}–{config.PAPER_CSS2_DD_MAX_PCT:g}%",
    )
    late = since > config.PAPER_CSS2_LATE_MIN
    megavol = pump.volume_ratio is not None and pump.volume_ratio >= config.PAPER_CSS2_MEGAVOL_RATIO
    checks["not_late_megavol"] = _check(
        not (late and megavol),
        _r(pump.volume_ratio, 2),
        f"после {config.PAPER_CSS2_LATE_MIN:g} мин объём < ×{config.PAPER_CSS2_MEGAVOL_RATIO:g}",
    )
    top = strong_top(klines, now_ms) if late else None
    checks["not_late_double_top"] = _check(
        top is None,
        bool(top),
        f"после {config.PAPER_CSS2_LATE_MIN:g} мин без двойной вершины",
    )
    forming = peak_on_open_15m(state, pump.peak_price, now_ms)
    checks["peak_not_forming"] = _check(not forming, forming, "хай не на открытой 15м")

    sell_shares: dict[str, float | None] = {}
    winners = 0
    buy_5 = None
    if tape is not None:
        for minutes in config.PAPER_SELL_WINDOWS_MIN:
            buy, sell = tape.minute_window(now_ms, minutes)
            share = sell / (buy + sell) * 100.0 if buy + sell > 0 else None
            sell_shares[f"{minutes}m"] = _r(share, 1)
            if share is not None and share > config.PAPER_CSS2_SELL_SHARE_MIN_PCT:
                winners += 1
        b5, s5 = tape.minute_window(now_ms, 5)
        if b5 + s5 > 0:
            buy_5 = b5 / (b5 + s5) * 100.0
    checks["sells_dominate"] = _check(
        winners >= 2,
        sell_shares,
        f"продажи > {config.PAPER_CSS2_SELL_SHARE_MIN_PCT:g}% в 2+ окнах",
    )
    checks["buy_share_5m"] = _check(
        buy_5 is not None and buy_5 <= config.PAPER_CSS2_BUY_SHARE_5M_MAX,
        _r(buy_5, 1),
        f"≤ {config.PAPER_CSS2_BUY_SHARE_5M_MAX:g}%",
    )

    px15 = price_change_pct(state, now_ms, 15)
    checks["price_15m_down"] = _check(px15 is not None and px15 <= 0, _r(px15, 2), "≤ 0%")

    liq_now = liq_peak = None
    if tape is not None:
        liq_now, liq_peak = short_liq_15m(tape, pump.peak_ts, now_ms)
    liq_ok = (
        liq_now is not None
        and liq_peak is not None
        and liq_peak > 0
        and liq_now <= liq_peak * config.PAPER_CSS2_SHORT_LIQ_MAX_RATIO
    )
    checks["short_liq_faded"] = _check(
        liq_ok,
        {"now_usd": None if liq_now is None else round(liq_now), "peak_usd": None if liq_peak is None else round(liq_peak)},
        f"сейчас ≤ {config.PAPER_CSS2_SHORT_LIQ_MAX_RATIO * 100:g}% от максимума с пика",
    )

    oi_1h = oi_change_pct(state.oi_points(), lookback_min=60)
    checks["oi_1h_flat"] = _check(
        oi_1h is not None and oi_1h <= config.PAPER_CSS2_OI_1H_MAX_PCT,
        _r(oi_1h, 2),
        f"≤ +{config.PAPER_CSS2_OI_1H_MAX_PCT:g}%",
    )

    btc_15 = price_change_pct(btc, now_ms, 15) if btc is not None else None
    alt_minus = (px15 - btc_15) if px15 is not None and btc_15 is not None else None
    checks["not_beating_btc"] = _check(
        alt_minus is not None and alt_minus <= 0,
        _r(alt_minus, 2),
        "монета − BTC ≤ 0 п.п.",
    )

    imbalance = book_imbalance_1pct(state)
    checks["book_asks"] = _check(imbalance is not None and imbalance <= 0, _r(imbalance, 3), "≤ 0")

    metrics.update(
        {
            "sell_share": sell_shares,
            "buy_share_5m": _r(buy_5, 1),
            "price_15m_pct": _r(px15, 2),
            "btc_15m_pct": _r(btc_15, 2),
            "alt_minus_btc_15m": _r(alt_minus, 2),
            "oi_1h_pct": _r(oi_1h, 2),
            "short_liq_now": None if liq_now is None else round(liq_now),
            "short_liq_peak": None if liq_peak is None else round(liq_peak),
            "imbalance_1pct": _r(imbalance, 3),
            "turnover_24h_usd": turnover,
            "funding_rate": state.funding_rate,
        }
    )
    score = float(sum(8.0 for key in CSS2_MANDATORY if checks[key]["ok"]))
    return Css2Evaluation(checks=checks, metrics=metrics, score=score)
