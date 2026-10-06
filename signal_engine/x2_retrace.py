"""Доска «2× откат»: рост ≥2× от min за 5d, LH на 1H/4H, OI↓, пробой EMA."""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from signal_engine.ema_breakdown import ema_breakdown_by_interval
from signal_engine.evaluate import Reading, evaluate
from signal_engine.pump_scan import price_24h_pct
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import absolute_high_since, lower_high_chain_count

_MS_5D = 5 * 24 * 3600 * 1000
_MS_24H = 24 * 3600 * 1000
_MS_1H = 3600 * 1000


def _eligible(state: SymbolState) -> bool:
    turnover = state.turnover_24h_usdt
    if turnover is None or turnover < config.UNIVERSE_MIN_TURNOVER_24H_USDT:
        return False
    if state.last_price is None or state.last_price <= 0:
        return False
    return True


def _pump_from_5d_min(state: SymbolState, now_ms: int) -> tuple[float, float, int] | None:
    """Множитель, min_low, timestamp дна (последний бар с этим low)."""
    bars = state.bars_htf.get("60") or []
    if len(bars) < 12:
        return None
    window_start = now_ms - _MS_5D
    in_window = [b for b in bars if b.timestamp >= window_start]
    if not in_window:
        return None
    min_low = min(b.low for b in in_window)
    if min_low <= 0:
        return None
    mult = float(state.last_price) / min_low
    if mult < config.X2_RETRACE_MIN_MULTIPLIER:
        return None
    valley_ts = max(b.timestamp for b in in_window if b.low == min_low)
    return mult, min_low, valley_ts


def _pullback_pct(
    bars_1h: list[Bar],
    pump_start_ts: int,
    now_ms: int,
    last_price: float,
) -> tuple[bool, float]:
    peak = absolute_high_since(bars_1h, pump_start_ts, "60", now_ms)
    if peak is None:
        return False, 0.0
    abs_high, _high_ts = peak
    if abs_high <= 0:
        return False, 0.0
    drop = (abs_high - last_price) / abs_high * 100.0
    if drop < config.X2_RETRACE_MIN_PULLBACK_PCT:
        return False, drop
    from signal_engine.swing_highs import closed_bars

    closed = closed_bars(bars_1h, "60", now_ms)
    recent = [b for b in closed if b.timestamp >= now_ms - _MS_24H]
    if len(recent) < 1:
        return False, drop
    high_24h = max(b.high for b in recent)
    if last_price >= high_24h * 0.998:
        return False, drop
    oldest = recent[0].close
    if now_ms - recent[0].timestamp < _MS_1H and drop < config.X2_RETRACE_MIN_PULLBACK_PCT * 2:
        return False, drop
    if oldest > 0 and last_price >= oldest and drop < config.X2_RETRACE_MIN_PULLBACK_PCT:
        return False, drop
    return True, drop


def _ema_depth_max(ema_map: dict[str, dict]) -> int:
    if not ema_map:
        return 0
    return max(int(item.get("depth") or 0) for item in ema_map.values())


def stage_for(
    *,
    multiplier: float,
    pullback_ok: bool,
    lh_1h: int,
    lh_4h: int,
    oi_drop: bool,
    ema_depth: int,
) -> int:
    if multiplier < config.X2_RETRACE_MIN_MULTIPLIER:
        return 0
    if not pullback_ok:
        return 1
    lh_ok = lh_1h >= 2 or lh_4h >= 2 or (lh_1h >= 1 and lh_4h >= 1)
    if not lh_ok:
        return 2
    if oi_drop and ema_depth >= 2:
        return 4
    if oi_drop or ema_depth >= 1:
        return 3
    return 2


@dataclass
class X2RetraceItem:
    symbol: str
    stage: int
    multiplier: float
    min_low_5d: float
    pump_start_ts: int
    pullback_pct: float
    lh_1h: int
    lh_4h: int
    last_price: float
    price_24h_pct: float | None
    turnover_24h_usdt: float
    oi_drop: bool
    oi_change_pct: float | None
    ema_depth: int
    ema_by_tf: dict[str, dict] = field(default_factory=dict)
    updated_at: int = 0

    def to_data(self) -> dict:
        col = config.X2_RETRACE_COLUMNS[self.stage]
        return {
            "symbol": self.symbol,
            "stage": self.stage,
            "color": col["color"],
            "status": col["status"],
            "label": col["label"],
            "multiplier": round(self.multiplier, 2),
            "min_low_5d": self.min_low_5d,
            "pump_start_ts": self.pump_start_ts,
            "pullback_pct": round(self.pullback_pct, 2),
            "lh_1h": self.lh_1h,
            "lh_4h": self.lh_4h,
            "last_price": self.last_price,
            "price_24h_pct": round(self.price_24h_pct, 2) if self.price_24h_pct is not None else None,
            "turnover_24h_usdt": self.turnover_24h_usdt,
            "oi_drop": self.oi_drop,
            "oi_change_pct": self.oi_change_pct,
            "ema_depth": self.ema_depth,
            "ema_by_tf": self.ema_by_tf,
            "updated_at": self.updated_at,
        }


def build_x2_retrace_board(states: dict[str, SymbolState], now_ms: int) -> dict:
    items: list[X2RetraceItem] = []
    for symbol, state in states.items():
        if not _eligible(state):
            continue
        pump = _pump_from_5d_min(state, now_ms)
        if pump is None:
            continue
        mult, min_low, pump_start = pump
        bars_1h = state.bars_htf.get("60") or []
        bars_4h = state.bars_htf.get("240") or []
        lh_1h = lower_high_chain_count(bars_1h, pump_start, "60", now_ms, config.X2_RETRACE_PIVOT_WING)
        lh_4h = lower_high_chain_count(bars_4h, pump_start, "240", now_ms, config.X2_RETRACE_PIVOT_WING)
        pullback_ok, pullback_pct = _pullback_pct(bars_1h, pump_start, now_ms, float(state.last_price))
        reading: Reading = evaluate(state, now_ms)
        ema_map = ema_breakdown_by_interval(state.bars_htf)
        ema_depth = _ema_depth_max(ema_map)
        stage = stage_for(
            multiplier=mult,
            pullback_ok=pullback_ok,
            lh_1h=lh_1h,
            lh_4h=lh_4h,
            oi_drop=reading.oi_drop,
            ema_depth=ema_depth,
        )
        if stage < 1:
            continue
        pct24 = price_24h_pct(state.price_24h_change)
        items.append(
            X2RetraceItem(
                symbol=symbol,
                stage=stage,
                multiplier=mult,
                min_low_5d=min_low,
                pump_start_ts=pump_start,
                pullback_pct=pullback_pct if pullback_ok else pullback_pct,
                lh_1h=lh_1h,
                lh_4h=lh_4h,
                last_price=float(state.last_price),
                price_24h_pct=pct24,
                turnover_24h_usdt=float(state.turnover_24h_usdt or 0),
                oi_drop=reading.oi_drop,
                oi_change_pct=reading.oi_change_pct,
                ema_depth=ema_depth,
                ema_by_tf=ema_map,
                updated_at=now_ms,
            )
        )
    grouped: dict[int, list[X2RetraceItem]] = {s: [] for s in (1, 2, 3, 4)}
    for item in items:
        grouped[item.stage].append(item)
    columns = []
    for stage in (4, 3, 2, 1):
        col = config.X2_RETRACE_COLUMNS[stage]
        ordered = sorted(
            grouped[stage],
            key=lambda row: (row.multiplier, row.lh_1h + row.lh_4h, row.ema_depth, row.pullback_pct),
            reverse=True,
        )
        columns.append({**col, "stage": stage, "signals": [row.to_data() for row in ordered]})
    return {"type": "x2_retrace_board", "timestamp": now_ms, "data": {"columns": columns}}
