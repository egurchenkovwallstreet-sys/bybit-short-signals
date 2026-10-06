"""Пробой EMA 50 / 100 / 200 вниз по закрытым свечам."""

from __future__ import annotations

from dataclasses import dataclass

from signal_engine.indicators import ema

EMA_PERIODS = (50, 100, 200)

INTERVAL_LABEL = {
    "15": "15m",
    "30": "30m",
    "60": "1H",
    "240": "4H",
}


@dataclass(frozen=True)
class EmaBreakdown:
    """depth: 0 — все EMA выше цены; 1 — под 50; 2 — под 100; 3 — под 200."""

    depth: int
    below_50: bool
    below_100: bool
    below_200: bool
    cross_50: bool
    cross_100: bool
    cross_200: bool

    def summary_ru(self) -> str:
        parts: list[str] = []
        if self.cross_50 or self.below_50:
            parts.append("пробита 50 EMA" if self.cross_50 else "ниже 50 EMA")
        if self.cross_100 or self.below_100:
            parts.append("пробита 100 EMA" if self.cross_100 else "ниже 100 EMA")
        if self.cross_200 or self.below_200:
            parts.append("пробита 200 EMA" if self.cross_200 else "ниже 200 EMA")
        if not parts:
            return "цена выше 50/100/200 EMA"
        return ", ".join(parts)


def analyze_ema_breakdown(closes: list[float]) -> EmaBreakdown | None:
    if len(closes) < max(EMA_PERIODS) + 2:
        return None
    series = {period: ema(closes, period) for period in EMA_PERIODS}
    i = len(closes) - 1
    prev = i - 1
    if any(series[p][i] is None or series[p][prev] is None for p in EMA_PERIODS):
        return None

    def crossed_below(period: int) -> bool:
        e = series[period]
        return closes[prev] >= e[prev] and closes[i] < e[i]

    below_50 = closes[i] < series[50][i]
    below_100 = closes[i] < series[100][i]
    below_200 = closes[i] < series[200][i]
    if below_200:
        depth = 3
    elif below_100:
        depth = 2
    elif below_50:
        depth = 1
    else:
        depth = 0

    return EmaBreakdown(
        depth=depth,
        below_50=below_50,
        below_100=below_100,
        below_200=below_200,
        cross_50=crossed_below(50),
        cross_100=crossed_below(100),
        cross_200=crossed_below(200),
    )


def ema_breakdown_by_interval(bars_htf: dict[str, list]) -> dict[str, dict]:
    """bars_htf: interval -> list of Bar-like with .close."""
    out: dict[str, dict] = {}
    for interval, label in INTERVAL_LABEL.items():
        bars = bars_htf.get(interval) or []
        closes = [float(bar.close) for bar in bars]
        reading = analyze_ema_breakdown(closes)
        if reading is None:
            continue
        out[label] = {
            "depth": reading.depth,
            "summary": reading.summary_ru(),
            "cross_50": reading.cross_50,
            "cross_100": reading.cross_100,
            "cross_200": reading.cross_200,
        }
    return out
