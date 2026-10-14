"""Cursor SS: шорт после быстрого пампа — затихание, вход только на дампе.

t20/p10/lt20 не использует этот модуль. Пик — абсолютный хай эпизода:
новая вершина сбрасывает затихание. Стоп/BE — в position (stop_style=css).
"""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.indicators import ema
from signal_engine.paper.detect import (
    HOUR_MS,
    MIN_MS,
    _check,
    _r,
    _volume_and_price,
    grade_for,
    leg_volume_ratio,
    merged_15m,
)
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars

CSS_MANDATORY = (
    "pump_volume",
    "pump_buys",
    "no_new_high_15m",
    "volume_fade",
    "buys_faded",
    "short_liq_faded",
    "sells_dominate",
    "dump_break",
    "drawdown_ok",
)

CSS_CHECK_LABELS = {
    "pump_volume": f"Объём на пампа ×{config.PAPER_CSS_VOLUME_MIN_RATIO:g}+",
    "pump_buys": f"Покупки на пампа ≥{config.PAPER_CSS_BUY_SHARE_MIN_PCT:g}%",
    "no_new_high_15m": "Закрытая 15м без нового хая",
    "volume_fade": "Объём затих после климакса",
    "buys_faded": "Агрессивные покупки упали",
    "short_liq_faded": "Ликвидации шортов затихли",
    "sells_dominate": "Продажи преобладают 5/10/15 мин",
    "dump_break": "Дамп: пробой низа полки",
    "drawdown_ok": f"Откат от пика ≤{config.PAPER_CSS_MAX_DRAWDOWN_PCT:g}%",
}


@dataclass
class CssPumpInfo:
    valley_price: float
    valley_ts: int
    peak_price: float
    peak_ts: int
    growth_pct: float
    volume_ratio: float | None = None
    volume_avg_ratio: float | None = None
    buy_share_pct: float | None = None
    tape_minutes: int = 0
    stall_low: float | None = None
    stall_high: float | None = None
    stall_frozen: bool = False

    @property
    def duration_ms(self) -> int:
        return max(0, self.peak_ts - self.valley_ts)

    def to_data(self) -> dict:
        return {
            "kind": "css",
            "trigger": "fast",
            "growth_pct": _r(self.growth_pct, 2),
            "valley_price": self.valley_price,
            "valley_ts": self.valley_ts,
            "peak_price": self.peak_price,
            "peak_ts": self.peak_ts,
            "duration_min": round(self.duration_ms / MIN_MS),
            "volume_ratio": _r(self.volume_ratio, 2),
            "volume_avg_ratio": _r(self.volume_avg_ratio, 2),
            "buy_share_pct": _r(self.buy_share_pct, 1),
            "tape_minutes": self.tape_minutes,
            "stall_low": self.stall_low,
            "stall_high": self.stall_high,
            "stall_frozen": self.stall_frozen,
        }


@dataclass
class CssEvaluation:
    checks: dict[str, dict]
    metrics: dict
    score: float

    @property
    def passed(self) -> bool:
        return all(self.checks[k]["ok"] for k in CSS_MANDATORY)

    @property
    def failed(self) -> list[str]:
        return [k for k in CSS_MANDATORY if not self.checks[k]["ok"]]

    @property
    def passed_count(self) -> int:
        return len(CSS_MANDATORY) - len(self.failed)

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
            "variants": [config.PAPER_CSS_VARIANT] if self.passed else [],
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


def find_css_pump(state: SymbolState, tape: SymbolTape | None, now_ms: int) -> CssPumpInfo | None:
    """Быстрый памп из базы: +12% за ≤6 ч, не многодневный грайнд."""
    bars15 = merged_15m(state)
    if len(bars15) < 8:
        return None
    last = float(state.last_price or 0)
    if last <= 0:
        return None
    lookback = now_ms - int(config.PAPER_CSS_LOOKBACK_HOURS * HOUR_MS)
    recent = [b for b in bars15 if b.timestamp >= lookback]
    if not recent:
        return None
    peak_bar = max(recent, key=lambda b: b.high)
    peak = peak_bar.high
    if peak <= 0:
        return None
    peak_ts = _precise_peak_ts(state, peak_bar.timestamp, peak)
    dd = (1.0 - last / peak) * 100.0
    if dd > config.PAPER_CSS_MAX_DRAWDOWN_PCT:
        return None
    if now_ms - peak_ts > int(config.PAPER_CSS_LIFETIME_HOURS * HOUR_MS):
        return None

    leg_ms = int(config.PAPER_CSS_MAX_LEG_HOURS * HOUR_MS)
    window = [b for b in bars15 if peak_ts - leg_ms <= b.timestamp <= peak_ts]
    if not window:
        return None
    valley = min(window, key=lambda b: b.low)
    if valley.low <= 0:
        return None
    growth = (peak / valley.low - 1.0) * 100.0
    if growth < config.PAPER_CSS_MIN_GROWTH_PCT:
        return None
    duration = peak_ts - valley.timestamp
    if duration <= 0 or duration > leg_ms:
        return None

    info = CssPumpInfo(
        valley_price=valley.low,
        valley_ts=valley.timestamp,
        peak_price=peak,
        peak_ts=peak_ts,
        growth_pct=growth,
    )
    info.volume_ratio, info.volume_avg_ratio = leg_volume_ratio(bars15, valley.timestamp, peak_ts)
    if tape is not None:
        buy, sell, covered = tape.buy_sell_between(valley.timestamp, peak_ts)
        info.tape_minutes = covered
        need = min(config.PAPER_CSS_TAPE_MIN_MINUTES, max(5, duration // MIN_MS))
        if covered >= need and buy + sell > 0:
            info.buy_share_pct = buy / (buy + sell) * 100.0
    _fill_stall(info, state, now_ms)
    return info


def refresh_css_peak(pump: CssPumpInfo, state: SymbolState, tape: SymbolTape | None, now_ms: int) -> bool:
    """Поднять хай, если появилась вторая нога. True если пик изменился."""
    fresh = find_css_pump(state, tape, now_ms)
    if fresh is None:
        return False
    if fresh.peak_price > pump.peak_price + 1e-12:
        pump.valley_price = fresh.valley_price
        pump.valley_ts = fresh.valley_ts
        pump.peak_price = fresh.peak_price
        pump.peak_ts = fresh.peak_ts
        pump.growth_pct = fresh.growth_pct
        pump.volume_ratio = fresh.volume_ratio
        pump.volume_avg_ratio = fresh.volume_avg_ratio
        pump.buy_share_pct = fresh.buy_share_pct
        pump.tape_minutes = fresh.tape_minutes
        pump.stall_low = fresh.stall_low
        pump.stall_high = fresh.stall_high
        pump.stall_frozen = False
        return True
    if not pump.stall_frozen:
        _fill_stall(pump, state, now_ms)
    return False


def _fill_stall(pump: CssPumpInfo, state: SymbolState, now_ms: int) -> None:
    """Полка под хаем: 1м после пика, без последних N минут (там может быть дамп)."""
    if pump.stall_frozen:
        return
    exclude = config.PAPER_CSS_DUMP_EXCLUDE_MIN * MIN_MS
    end = now_ms - exclude
    pause = [b for b in state.bars_1m if pump.peak_ts < b.timestamp < end]
    if not pause:
        pump.stall_low = None
        pump.stall_high = None
        return
    pump.stall_low = min(b.low for b in pause)
    pump.stall_high = max(b.high for b in pause)


def evaluate_css(
    state: SymbolState,
    tape: SymbolTape,
    pump: CssPumpInfo,
    klines: dict[str, list[Bar]],
    now_ms: int,
) -> CssEvaluation:
    checks: dict[str, dict] = {}
    last = float(state.last_price or pump.peak_price)
    dd = (1.0 - last / pump.peak_price) * 100.0 if pump.peak_price > 0 else None
    since_peak_min = (now_ms - pump.peak_ts) / MIN_MS
    metrics: dict = {
        "pump": pump.to_data(),
        "last_price": last,
        "drawdown_from_peak_pct": _r(dd, 2),
        "since_peak_min": round(since_peak_min),
    }

    vr = pump.volume_ratio
    checks["pump_volume"] = _check(
        vr is not None and vr >= config.PAPER_CSS_VOLUME_MIN_RATIO,
        _r(vr, 2),
        f"≥ ×{config.PAPER_CSS_VOLUME_MIN_RATIO:g}",
    )
    bs = pump.buy_share_pct
    buys_ok = bs is None or bs >= config.PAPER_CSS_BUY_SHARE_MIN_PCT
    checks["pump_buys"] = _check(
        buys_ok,
        _r(bs, 1) if bs is not None else f"нет ленты ({pump.tape_minutes} мин)",
        f"≥ {config.PAPER_CSS_BUY_SHARE_MIN_PCT:g}% или нет ленты",
    )

    closed15 = closed_bars(klines.get("15") or merged_15m(state), "15", now_ms)
    last_closed = closed15[-1] if closed15 else None
    no_new_high = (
        last_closed is not None
        and last_closed.high <= pump.peak_price * 1.0001
        and since_peak_min >= config.PAPER_CSS_QUIET_MIN_MINUTES
        and last_closed.timestamp + 15 * MIN_MS <= now_ms
    )
    checks["no_new_high_15m"] = _check(
        no_new_high,
        {
            "since_peak_min": round(since_peak_min),
            "closed_high": last_closed.high if last_closed else None,
        },
        f"≥ {config.PAPER_CSS_QUIET_MIN_MINUTES:g} мин, закрытая 15м не выше пика",
    )

    vol_ratio, price_20m = _volume_and_price(state)
    fading = vol_ratio is not None and vol_ratio <= config.PAPER_CSS_VOLUME_FADE_MAX_RATIO
    checks["volume_fade"] = _check(
        fading,
        {"ratio": _r(vol_ratio, 2), "price_20m_pct": _r(price_20m, 2)},
        f"объём 20 мин ≤ {config.PAPER_CSS_VOLUME_FADE_MAX_RATIO * 100:g}% пика",
    )

    cur_buy, _ = tape.minute_window(now_ms, 15)
    peak_buy = tape.peak_buy_window(now_ms, 15)
    buy_ratio = cur_buy / peak_buy if peak_buy > 0 else None
    checks["buys_faded"] = _check(
        buy_ratio is not None and buy_ratio <= config.PAPER_BUYS_FADE_MAX_RATIO,
        {"ratio": _r(buy_ratio, 2), "last15_usd": round(cur_buy), "peak15_usd": round(peak_buy)},
        f"покупки 15 мин ≤ {config.PAPER_BUYS_FADE_MAX_RATIO * 100:g}% от пика",
    )

    short_liq = tape.liq_series(now_ms, config.PAPER_SHORT_LIQ_WINDOW_MIN, "short")
    liq_peak = max(short_liq) if short_liq else 0.0
    liq_now = max(short_liq[-2:]) if short_liq else 0.0
    fade = 1.0 if liq_peak <= 0 else 1.0 - liq_now / liq_peak
    checks["short_liq_faded"] = _check(
        fade >= config.PAPER_SHORT_LIQ_FADE_MIN,
        {"fade_pct": round(fade * 100), "peak_usd": round(liq_peak), "now_usd": round(liq_now)},
        f"поток упал ≥ {config.PAPER_SHORT_LIQ_FADE_MIN * 100:g}%",
    )

    sell_shares: dict[str, float | None] = {}
    winners = 0
    sell_need = config.PAPER_CSS_SELL_SHARE_MIN_PCT
    for minutes in config.PAPER_SELL_WINDOWS_MIN:
        b, s = tape.minute_window(now_ms, minutes)
        share = s / (b + s) * 100.0 if b + s > 0 else None
        sell_shares[f"{minutes}m"] = _r(share, 1)
        if share is not None and share > sell_need:
            winners += 1
    checks["sells_dominate"] = _check(
        winners >= config.PAPER_SELL_WINDOWS_REQUIRED,
        sell_shares,
        f"продажи > {sell_need:g}% в {config.PAPER_SELL_WINDOWS_REQUIRED}+ окнах",
    )

    if not pump.stall_frozen:
        _fill_stall(pump, state, now_ms)
        if (
            checks["no_new_high_15m"]["ok"]
            and pump.stall_low is not None
            and last >= pump.stall_low
        ):
            pump.stall_frozen = True
    stall_low = pump.stall_low
    dump_ok = stall_low is not None and last < stall_low
    checks["dump_break"] = _check(
        dump_ok,
        {
            "last": last,
            "stall_low": stall_low,
            "stall_high": pump.stall_high,
            "frozen": pump.stall_frozen,
        },
        "цена ниже низа полки после затихания",
    )

    checks["drawdown_ok"] = _check(
        dd is not None and dd <= config.PAPER_CSS_MAX_DRAWDOWN_PCT,
        _r(dd, 2),
        f"≤ {config.PAPER_CSS_MAX_DRAWDOWN_PCT:g}% от пика",
    )

    bars15 = closed_bars(klines.get("15") or merged_15m(state), "15", now_ms)
    closes = [b.close for b in bars15]
    ema50 = ema(closes, 50)
    ema50_val = ema50[-1] if ema50 else None
    ema_broken = bool(ema50_val is not None and closes and closes[-1] < ema50_val)

    metrics.update(
        {
            "range_pct": _r(
                ((pump.stall_high - stall_low) / pump.stall_high * 100.0)
                if pump.stall_high and stall_low
                else None,
                2,
            ),
            "sell_share": sell_shares,
            "volume_ratio_20m": _r(vol_ratio, 2),
            "price_20m_pct": _r(price_20m, 2),
            "buys_fade_ratio": _r(buy_ratio, 2),
            "short_liq_fade_pct": round(fade * 100),
            "ema50_15m": ema50_val,
            "ema50_15m_broken": ema_broken,
            "oi_1h_pct": None,
            "oi_4h_pct": None,
            "funding_rate": state.funding_rate,
            "turnover_24h_usd": state.turnover_24h_usdt,
        }
    )
    score = float(checks["dump_break"]["ok"]) * 20.0 + checks["no_new_high_15m"]["ok"] * 15.0
    score += sum(10.0 for k in CSS_MANDATORY if checks[k]["ok"])
    if ema_broken:
        score += 5.0
    return CssEvaluation(checks=checks, metrics=metrics, score=score)
