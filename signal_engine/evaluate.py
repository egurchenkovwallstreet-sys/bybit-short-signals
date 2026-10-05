"""Сводит пять подтверждений и дополнительные признаки в одно чтение.

Колонка — это число галочек:
1 памп, 2 ликвидации затихли, 3 OI падает, 4 объём спал, 5 свуп на 1H/4H/1D.
CVD, taker, OBV, funding и круглый уровень в эту пятёрку не входят.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from signal_engine.flow import (
    cvd_bearish,
    funding_extreme,
    obv_bearish,
    oi_change_pct,
    oi_falling,
    taker_ratio,
    taker_sellers_control,
    volume_faded,
)
from signal_engine.levels import (
    INTERVAL_LABEL,
    INTERVAL_MS,
    best_quality,
    candle_swept_level,
    levels_align,
    nearest_round_levels,
    round_level_confirmed,
    sweep_on_timeframe,
)
from signal_engine.liquidations import liquidations_faded, window_notionals
from signal_engine.pump import detect_pump
from signal_engine.state import SymbolState


@dataclass
class Reading:
    price_change_5m: float | None = None
    price_change_15m: float | None = None
    volume_ratio: float | None = None
    rsi: float | None = None
    pump: bool = False
    liquidations_faded: bool = False
    oi_drop: bool = False
    oi_change_pct: float | None = None
    volume_faded: bool = False
    sweep: bool = False
    sweep_timeframes: list[str] = field(default_factory=list)
    mega_level: bool = False
    round_level: bool = False
    cvd_divergence: bool = False
    taker_ratio: float | None = None
    obv_divergence: bool = False
    funding_rate: float | None = None
    quality: float = 0
    tf_match: int = 0
    chart_levels: list = field(default_factory=list)
    round_prices: list = field(default_factory=list)

    def strength(self, pump_latched: bool) -> int:
        points = int(pump_latched or self.pump)
        points += int(self.liquidations_faded)
        points += int(self.oi_drop)
        points += int(self.volume_faded)
        points += int(self.sweep)
        return min(5, points)

    def extra_count(self) -> int:
        return int(self.cvd_divergence) + int(taker_sellers_control(self.taker_ratio)) + int(
            self.obv_divergence
        ) + int(funding_extreme(self.funding_rate)) + int(self.round_level)


def evaluate(state: SymbolState, now_ms: int) -> Reading:
    closes = state.closes_1m()
    volumes = state.volumes_1m()
    # Цена последней сделки точнее закрытия минутной свечи.
    if state.last_price is not None and closes:
        closes = closes[:-1] + [state.last_price]
    pump = detect_pump(closes, volumes)
    oi_points = state.oi_points()
    oi_change = oi_change_pct(oi_points)
    ratio = taker_ratio(state.taker_buy, state.taker_sell, now_ms)
    if ratio is not None and ratio == float("inf"):
        ratio = None

    swept_labels: list[str] = []
    levels_by_label: dict[str, list] = {}
    candle_by_label: dict[str, object] = {}
    quality = 0
    for interval in config.HTF_INTERVALS:
        candles = state.htf_candles(interval)
        swept, levels, candle = sweep_on_timeframe(candles, now_ms, INTERVAL_MS[interval])
        label = INTERVAL_LABEL[interval]
        levels_by_label[label] = levels
        candle_by_label[label] = candle
        if swept:
            swept_labels.append(label)
            quality = max(quality, best_quality(levels, True, candle))

    if quality == 0:
        for levels in levels_by_label.values():
            quality = max(quality, best_quality(levels, False, None))

    mega = levels_align(levels_by_label.get("4H", []), levels_by_label.get("1D", []))
    tf_match = len(swept_labels)
    if mega and tf_match < 2:
        tf_match = 2
    if mega and "4H" in swept_labels and "1D" in swept_labels:
        tf_match = 3
    tf_match = min(tf_match, 3)

    candles_1m = [bar.as_candle() for bar in state.bars_1m]
    chart_levels: list[dict] = []
    for label, levels in levels_by_label.items():
        candle = candle_by_label.get(label)
        ranked = sorted(
            (level for level in levels if level.kind != "broken"),
            key=lambda level: level.score,
            reverse=True,
        )
        for level in ranked[:5]:
            chart_levels.append(
                {
                    "price": level.price,
                    "kind": level.kind,
                    "timeframe": label,
                    "swept": bool(candle and candle_swept_level(candle, level)),
                }
            )
    round_prices = (
        nearest_round_levels(state.last_price)
        if state.last_price is not None and state.last_price > 0
        else []
    )
    return Reading(
        price_change_5m=pump.price_change_5m,
        price_change_15m=pump.price_change_15m,
        volume_ratio=pump.volume_ratio,
        rsi=pump.rsi,
        pump=pump.matched,
        liquidations_faded=liquidations_faded(window_notionals(state.liq_notional, now_ms)),
        oi_drop=oi_falling(oi_points),
        oi_change_pct=oi_change,
        volume_faded=volume_faded(volumes),
        sweep=bool(swept_labels),
        sweep_timeframes=swept_labels,
        mega_level=mega,
        round_level=round_level_confirmed(candles_1m),
        cvd_divergence=cvd_bearish(state.cvd_delta, pump.price_change_15m, now_ms),
        taker_ratio=ratio,
        obv_divergence=obv_bearish(closes, volumes, pump.price_change_15m),
        funding_rate=state.funding_rate,
        quality=quality,
        tf_match=tf_match,
        chart_levels=chart_levels,
        round_prices=round_prices,
    )
