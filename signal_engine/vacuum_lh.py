"""Пылесос (LH-скан): до пяти LH на 1H; в список — цена ниже трёх последних вершин."""

from __future__ import annotations

import config
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars, pivot_highs

INTERVAL_1H = "60"
_MS_15M = 900_000


def _meets_turnover(state: SymbolState) -> bool:
    turnover = state.turnover_24h_usdt
    if turnover is None:
        return False
    return turnover >= config.VACUUM_LH_MIN_TURNOVER_24H_USDT


def last_lower_high_peaks(
    bars_1h: list[Bar],
    now_ms: int,
    *,
    count: int | None = None,
    wing: int | None = None,
) -> list[dict]:
    """До `count` последних pivot-high, каждый ниже предыдущего в цепочке (от старых к новым)."""
    n = count if count is not None else config.VACUUM_LH_PEAK_COUNT
    w = wing if wing is not None else config.VACUUM_LH_PIVOT_WING
    lookback_ms = config.VACUUM_LH_LOOKBACK_DAYS * 24 * 3_600_000
    closed = closed_bars(bars_1h, INTERVAL_1H, now_ms)
    segment = [b for b in closed if b.timestamp >= now_ms - lookback_ms]
    peaks = pivot_highs(segment, w)
    if len(peaks) < 2:
        return []
    chain: list[dict] = [peaks[-1]]
    for p in reversed(peaks[:-1]):
        if float(p["price"]) > float(chain[0]["price"]):
            chain.insert(0, p)
        if len(chain) >= n:
            break
    if len(chain) < 2:
        return []
    if len(chain) > n:
        chain = chain[-n:]
    return chain


def project_peaks_to_15m(peaks: list[dict]) -> list[dict]:
    """Время 1H → начало соответствующей 15m свечи (для маркеров на 15m)."""
    out: list[dict] = []
    for i, p in enumerate(peaks, start=1):
        t1h = int(p["time"])
        t15 = (t1h // _MS_15M) * _MS_15M
        out.append(
            {
                "index": i,
                "price": round(float(p["price"]), 8),
                "time_ms": t1h,
                "time_15m_ms": t15,
            }
        )
    return out


def price_below_recent_peaks(
    last_price: float,
    peaks: list[dict],
    *,
    last_n: int | None = None,
) -> bool:
    """Цена строго ниже каждой из `last_n` самых новых вершин цепочки."""
    n = last_n if last_n is not None else config.VACUUM_LH_PRICE_BELOW_LAST
    if not peaks or last_price is None or last_price <= 0 or n < 1:
        return False
    if len(peaks) < n:
        return False
    recent = peaks[-n:]
    return float(last_price) < min(float(p["price"]) for p in recent)


def scan_symbol(state: SymbolState, now_ms: int) -> dict | None:
    if not _meets_turnover(state):
        return None
    last = state.last_price
    if last is None or last <= 0:
        return None
    bars = state.bars_htf.get(INTERVAL_1H) or []
    if len(bars) < config.VACUUM_LH_MIN_1H_BARS:
        return None
    need = config.VACUUM_LH_PRICE_BELOW_LAST
    peaks = last_lower_high_peaks(bars, now_ms)
    if len(peaks) < need:
        return None
    if not price_below_recent_peaks(float(last), peaks):
        return None
    projected = project_peaks_to_15m(peaks)
    nearest = projected[-1]["price"]
    gap_pct = (nearest - float(last)) / nearest * 100.0 if nearest > 0 else 0.0
    return {
        "symbol": state.symbol,
        "last_price": float(last),
        "turnover_24h_usdt": float(state.turnover_24h_usdt or 0),
        "peak_count": len(projected),
        "peaks": projected,
        "nearest_peak_price": nearest,
        "gap_to_nearest_pct": round(gap_pct, 2),
        "updated_at": now_ms,
    }


def build_vacuum_lh_board(states: dict[str, SymbolState], now_ms: int) -> dict:
    signals: list[dict] = []
    for state in states.values():
        row = scan_symbol(state, now_ms)
        if row is not None:
            signals.append(row)
    signals.sort(key=lambda r: (-float(r["gap_to_nearest_pct"]), r["symbol"]))
    return {"type": "vacuum_lh_board", "timestamp": now_ms, "data": {"signals": signals}}
