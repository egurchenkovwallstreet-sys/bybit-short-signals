"""EMA50 5м шорт: тот же поиск пампа, что у t20/p10; вход по закрытию 5м под EMA50.

t20/p10/lt20/css/sc10 этот модуль не используют.
"""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.indicators import ema
from signal_engine.paper.detect import MIN_MS, PumpInfo, _check, _r, grade_for
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState

STEP_5M = 5 * MIN_MS

E5S_MANDATORY = (
    "ema50_5m_break",
    "sells_5_15",
    "short_liq_faded",
    "peak_age",
)

E5S_CHECK_LABELS = {
    "ema50_5m_break": "Закрытая 5м пробила EMA50 вниз",
    "sells_5_15": f"Продажи > {config.PAPER_E5S_SELL_SHARE_MIN_PCT:g}% за 5 и 15 мин",
    "short_liq_faded": "Ликвидации шортов затихли",
    "peak_age": f"Пик ≥ {config.PAPER_E5S_PEAK_BARS_5M} свечей 5м назад",
}


@dataclass
class E5sEvaluation:
    checks: dict[str, dict]
    metrics: dict
    score: float
    strict_btc: bool = False

    @property
    def passed(self) -> bool:
        return all(self.checks[k]["ok"] for k in E5S_MANDATORY)

    @property
    def failed(self) -> list[str]:
        return [k for k in E5S_MANDATORY if not self.checks[k]["ok"]]

    @property
    def passed_count(self) -> int:
        return len(E5S_MANDATORY) - len(self.failed)

    def to_data(self) -> dict:
        return {
            "checks": self.checks,
            "metrics": self.metrics,
            "score": round(self.score, 1),
            "grade": grade_for(self.score),
            "strict_btc": self.strict_btc,
            "passed": self.passed,
            "passed_count": self.passed_count,
            "failed": self.failed,
            "variants": [config.PAPER_E5S_VARIANT] if self.passed else [],
            "entry_blocked": [],
        }


def merged_5m(state: SymbolState, klines: dict[str, list[Bar]] | None = None) -> list[Bar]:
    """5м из REST/HTF, свежий хвост — из минуток."""
    by_ts: dict[int, Bar] = {}
    for src in ((klines or {}).get("5") or [], state.bars_htf.get("5") or []):
        for bar in src:
            by_ts[int(bar.timestamp)] = Bar(bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume)
    minutes = state.bars_1m
    if minutes:
        first = minutes[0].timestamp
        groups: dict[int, list[Bar]] = {}
        for bar in minutes:
            key = (bar.timestamp // STEP_5M) * STEP_5M
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


def closed_5m(bars: list[Bar], now_ms: int) -> list[Bar]:
    return [b for b in bars if b.timestamp + STEP_5M <= now_ms]


def evaluate_e5s(
    state: SymbolState,
    tape: SymbolTape,
    pump: PumpInfo,
    klines: dict[str, list[Bar]],
    now_ms: int,
) -> E5sEvaluation:
    checks: dict[str, dict] = {}
    last = float(state.last_price or pump.peak_price)
    since_peak_min = (now_ms - pump.peak_ts) / MIN_MS
    bars_since_peak = (now_ms - pump.peak_ts) // STEP_5M
    metrics: dict = {
        "pump": pump.to_data(),
        "last_price": last,
        "since_peak_min": round(since_peak_min),
        "bars_5m_since_peak": int(bars_since_peak),
    }

    bars = closed_5m(merged_5m(state, klines), now_ms)
    period = config.PAPER_E5S_EMA_PERIOD
    closes = [b.close for b in bars]
    series = ema(closes, period)
    ema_now = series[-1] if series else None
    ema_prev = series[-2] if series and len(series) >= 2 else None
    last_bar = bars[-1] if bars else None
    prev_bar = bars[-2] if len(bars) >= 2 else None
    crossed = (
        last_bar is not None
        and ema_now is not None
        and last_bar.close < ema_now
        and (
            (prev_bar is not None and ema_prev is not None and prev_bar.close >= ema_prev)
            or last_bar.high >= ema_now
        )
    )
    checks["ema50_5m_break"] = _check(
        crossed,
        {
            "close": _r(last_bar.close, 8) if last_bar else None,
            "high": _r(last_bar.high, 8) if last_bar else None,
            "ema50": _r(ema_now, 8),
            "prev_close": _r(prev_bar.close, 8) if prev_bar else None,
            "bars": len(bars),
        },
        "закрытая 5м ниже EMA50 после пробоя",
    )

    need = config.PAPER_E5S_SELL_SHARE_MIN_PCT
    sell_shares: dict[str, float | None] = {}
    for minutes in (5, 15):
        b, s = tape.minute_window(now_ms, minutes)
        share = s / (b + s) * 100.0 if b + s > 0 else None
        sell_shares[f"{minutes}m"] = _r(share, 1)
    s5, s15 = sell_shares.get("5m"), sell_shares.get("15m")
    checks["sells_5_15"] = _check(
        s5 is not None and s15 is not None and s5 > need and s15 > need,
        sell_shares,
        f"продажи > {need:g}% в окнах 5 и 15 мин",
    )
    metrics["sell_share"] = sell_shares

    short_liq = tape.liq_series(now_ms, config.PAPER_SHORT_LIQ_WINDOW_MIN, "short")
    liq_peak = max(short_liq) if short_liq else 0.0
    liq_now = max(short_liq[-2:]) if short_liq else 0.0
    fade = 1.0 if liq_peak <= 0 else 1.0 - liq_now / liq_peak
    checks["short_liq_faded"] = _check(
        fade >= config.PAPER_SHORT_LIQ_FADE_MIN,
        {"fade_pct": round(fade * 100), "peak_usd": round(liq_peak), "now_usd": round(liq_now)},
        f"поток упал ≥ {config.PAPER_SHORT_LIQ_FADE_MIN * 100:g}%",
    )

    need_bars = config.PAPER_E5S_PEAK_BARS_5M
    checks["peak_age"] = _check(
        bars_since_peak >= need_bars,
        {"bars_5m": int(bars_since_peak), "since_peak_min": round(since_peak_min)},
        f"≥ {need_bars} закрытых/прошедших 5м с пика",
    )

    score = 25.0 * sum(1 for k in E5S_MANDATORY if checks[k]["ok"])
    if ema_now is not None and last_bar is not None and last_bar.close < ema_now:
        score += 5.0
    metrics["ema50_5m"] = _r(ema_now, 8)
    return E5sEvaluation(checks=checks, metrics=metrics, score=score)
