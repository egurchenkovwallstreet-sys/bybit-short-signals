"""Карточка сигнала, которую движок пишет в SQLite и публикует в Redis."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Signal:
    symbol: str
    created_at: int
    updated_at: int
    entry_price: float
    last_price: float
    strength: int
    rating: float
    probability: float
    quality: float
    tf_match: int
    extra: int
    color: str
    status: str
    label: str
    price_change_5m: float | None = None
    price_change_15m: float | None = None
    volume_ratio: float | None = None
    rsi: float | None = None
    liquidations_faded: bool = False
    oi_drop: bool = False
    oi_change_pct: float | None = None
    oi_change_1h_pct: float | None = None
    oi_change_4h_pct: float | None = None
    volume_faded: bool = False
    sweep: bool = False
    sweep_timeframes: list[str] = field(default_factory=list)
    mega_level: bool = False
    round_level: bool = False
    cvd_divergence: bool = False
    taker_ratio: float | None = None
    obv_divergence: bool = False
    funding_rate: float | None = None
    outcome: str | None = None
    exit_price: float | None = None
    exit_at: int | None = None
    pnl_pct: float | None = None
    id: int | None = None
    chart_levels: list = field(default_factory=list)
    round_prices: list = field(default_factory=list)

    def checks(self) -> dict[str, bool]:
        # Памп зафиксирован в момент создания и остаётся первой галочкой.
        return {
            "pump": True,
            "liquidations_faded": self.liquidations_faded,
            "oi_drop": self.oi_drop,
            "volume_faded": self.volume_faded,
            "sweep": self.sweep,
        }

    def extras(self) -> dict[str, bool]:
        taker_seller = self.taker_ratio is not None and self.taker_ratio < 1.0
        return {
            "cvd_divergence": self.cvd_divergence,
            "taker_seller": taker_seller,
            "obv_divergence": self.obv_divergence,
            "funding_extreme": self._funding_extreme(),
            "round_level": self.round_level,
        }

    def _funding_extreme(self) -> bool:
        import config

        return self.funding_rate is not None and self.funding_rate >= config.FUNDING_EXTREME_RATE

    def to_data(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entry_price": self.entry_price,
            "last_price": self.last_price,
            "strength": self.strength,
            "rating": self.rating,
            "probability": self.probability,
            "quality": self.quality,
            "tf_match": self.tf_match,
            "extra": self.extra,
            "color": self.color,
            "status": self.status,
            "label": self.label,
            "checks": self.checks(),
            "extras": self.extras(),
            "price_change_5m": self.price_change_5m,
            "price_change_15m": self.price_change_15m,
            "volume_ratio": self.volume_ratio,
            "rsi": self.rsi,
            "oi_change_pct": self.oi_change_pct,
            "oi_change_1h_pct": self.oi_change_1h_pct,
            "oi_change_4h_pct": self.oi_change_4h_pct,
            "sweep_timeframes": list(self.sweep_timeframes),
            "mega_level": self.mega_level,
            "taker_ratio": self.taker_ratio,
            "funding_rate": self.funding_rate,
            "outcome": self.outcome,
            "exit_price": self.exit_price,
            "exit_at": self.exit_at,
            "pnl_pct": self.pnl_pct,
            "chart_levels": list(self.chart_levels),
            "round_prices": list(self.round_prices),
        }

    def to_message(self, event: str, timestamp: int) -> dict:
        data = self.to_data()
        data["event"] = event
        return {
            "type": "signal",
            "symbol": self.symbol,
            "timestamp": timestamp,
            "data": data,
        }
