"""Доска «Памп-скан»: лидеры роста за 24ч и стадии ослабления перед шортом."""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from signal_engine.ema_breakdown import ema_breakdown_by_interval
from signal_engine.evaluate import Reading, evaluate
from signal_engine.flow import funding_extreme, taker_sellers_control
from signal_engine.state import SymbolState


def price_24h_pct(raw: float | None) -> float | None:
    """Bybit price24hPcnt — доля (0.35 = +35%). Уже в процентах — оставляем."""
    if raw is None:
        return None
    if abs(raw) <= 2.0:
        return raw * 100.0
    return raw


def is_gainer_candidate(state: SymbolState) -> bool:
    turnover = state.turnover_24h_usdt
    if turnover is None or turnover < config.UNIVERSE_MIN_TURNOVER_24H_USDT:
        return False
    pct = price_24h_pct(state.price_24h_change)
    return pct is not None and pct >= config.PUMP_SCAN_MIN_24H_PCT


def _weakening_score(reading: Reading, now_ms: int, state: SymbolState) -> int:
    score = 0
    score += int(reading.liquidations_faded)
    score += int(reading.oi_drop)
    score += int(reading.volume_faded)
    score += int(reading.cvd_divergence)
    score += int(taker_sellers_control(reading.taker_ratio))
    score += int(reading.obv_divergence)
    if funding_extreme(reading.funding_rate):
        score += 1
    return score


def _ema_depth_max(ema_map: dict[str, dict]) -> int:
    if not ema_map:
        return 0
    return max(int(item.get("depth") or 0) for item in ema_map.values())


def stage_for(reading: Reading, state: SymbolState, now_ms: int, ema_map: dict[str, dict]) -> int:
    weaken = _weakening_score(reading, now_ms, state)
    ema_depth = _ema_depth_max(ema_map)
    if reading.sweep or weaken >= 4 or ema_depth >= 3:
        return 4
    if weaken >= 3 or ema_depth >= 2:
        return 3
    if weaken >= 1 or ema_depth >= 1:
        return 2
    return 1


@dataclass
class PumpScanItem:
    symbol: str
    stage: int
    last_price: float
    price_24h_pct: float
    turnover_24h_usdt: float
    weaken_score: int
    ema_depth: int
    reading: Reading
    ema_by_tf: dict[str, dict] = field(default_factory=dict)
    updated_at: int = 0

    def to_data(self) -> dict:
        col = config.PUMP_SCAN_COLUMNS[self.stage]
        r = self.reading
        return {
            "symbol": self.symbol,
            "stage": self.stage,
            "color": col["color"],
            "status": col["status"],
            "label": col["label"],
            "last_price": self.last_price,
            "price_24h_pct": round(self.price_24h_pct, 2),
            "turnover_24h_usdt": self.turnover_24h_usdt,
            "weaken_score": self.weaken_score,
            "ema_depth": self.ema_depth,
            "updated_at": self.updated_at,
            "liquidations_faded": r.liquidations_faded,
            "oi_drop": r.oi_drop,
            "oi_change_pct": r.oi_change_pct,
            "volume_faded": r.volume_faded,
            "volume_ratio": r.volume_ratio,
            "cvd_divergence": r.cvd_divergence,
            "taker_ratio": r.taker_ratio,
            "funding_rate": r.funding_rate,
            "sweep": r.sweep,
            "rsi": r.rsi,
            "ema_by_tf": self.ema_by_tf,
        }


def build_pump_scan_board(states: dict[str, SymbolState], now_ms: int) -> dict:
    items: list[PumpScanItem] = []
    for symbol, state in states.items():
        if not is_gainer_candidate(state):
            continue
        if state.last_price is None or state.last_price <= 0:
            continue
        pct = price_24h_pct(state.price_24h_change)
        if pct is None:
            continue
        reading = evaluate(state, now_ms)
        ema_map = ema_breakdown_by_interval(state.bars_htf)
        weaken = _weakening_score(reading, now_ms, state)
        ema_depth = _ema_depth_max(ema_map)
        stage = stage_for(reading, state, now_ms, ema_map)
        items.append(
            PumpScanItem(
                symbol=symbol,
                stage=stage,
                last_price=state.last_price,
                price_24h_pct=pct,
                turnover_24h_usdt=float(state.turnover_24h_usdt or 0),
                weaken_score=weaken,
                ema_depth=ema_depth,
                reading=reading,
                ema_by_tf=ema_map,
                updated_at=now_ms,
            )
        )
    grouped: dict[int, list[PumpScanItem]] = {s: [] for s in (1, 2, 3, 4)}
    for item in items:
        grouped[item.stage].append(item)
    columns = []
    for stage in (4, 3, 2, 1):
        col = config.PUMP_SCAN_COLUMNS[stage]
        ordered = sorted(
            grouped[stage],
            key=lambda row: (row.weaken_score + row.ema_depth, row.price_24h_pct),
            reverse=True,
        )
        columns.append({**col, "stage": stage, "signals": [row.to_data() for row in ordered]})
    return {"type": "pump_scan_board", "timestamp": now_ms, "data": {"columns": columns}}
