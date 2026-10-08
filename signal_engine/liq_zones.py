"""Оценка зон ликвидации лонгов/шортов (модель OI + история allLiquidation).

Биржа не отдаёт будущие уровни — это приближение для UI, не официальная карта Bybit.
"""

from __future__ import annotations

import time
from typing import Any

# Isolated USDT-perp, упрощённая формула от mark/entry.
LEVERAGE_WEIGHTS: tuple[tuple[int, float], ...] = ((10, 0.45), (20, 0.35), (50, 0.20))
MMR = 0.005
DEFAULT_DEPTH_PCT = 0.35
HIST_WINDOW_MS = 48 * 3600 * 1000
MAX_ZONES_PER_SIDE = 28
BIN_FRAC = 0.0025


def isolated_liq_long(entry: float, leverage: float) -> float:
    if entry <= 0 or leverage <= 0:
        return 0.0
    return entry * (1.0 - (1.0 / leverage) * (1.0 - MMR))


def isolated_liq_short(entry: float, leverage: float) -> float:
    if entry <= 0 or leverage <= 0:
        return 0.0
    return entry * (1.0 + (1.0 / leverage) * (1.0 - MMR))


def _bin_price(price: float, mark: float) -> float:
    step = max(mark * BIN_FRAC, 1e-12)
    return round(price / step) * step


def _num(raw: Any) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def _ts_ms(raw: Any) -> int | None:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n if n > 1_000_000_000_000 else n * 1000


def _candle_at_or_before(candles: list[dict[str, Any]], ts_ms: int) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_ts = -1
    for c in candles:
        t = _ts_ms(c.get("timestamp") or c.get("time"))
        if t is None or t > ts_ms:
            continue
        if t >= best_ts:
            best_ts = t
            best = c
    return best


def _taker_weights(taker_buy: float, taker_sell: float) -> tuple[float, float]:
    total = taker_buy + taker_sell
    if total <= 0:
        return 0.5, 0.5
    long_w = taker_buy / total
    return long_w, 1.0 - long_w


def _add_bin(bins: dict[tuple[str, float], float], side: str, price: float, mark: float, notional: float) -> None:
    if notional <= 0 or price <= 0 or mark <= 0:
        return
    key = (side, _bin_price(price, mark))
    bins[key] = bins.get(key, 0.0) + notional


def _model_from_oi(
    oi_rows: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    mark: float,
    long_w: float,
    short_w: float,
) -> dict[tuple[str, float], float]:
    bins: dict[tuple[str, float], float] = {}
    if len(oi_rows) < 2 or not candles:
        return bins
    sorted_oi = sorted(
        [(t, v) for row in oi_rows if (t := _ts_ms(row.get("timestamp"))) and (v := _num(row.get("open_interest")))],
        key=lambda x: x[0],
    )
    if len(sorted_oi) < 2:
        return bins
    for i in range(1, len(sorted_oi)):
        t_prev, oi_prev = sorted_oi[i - 1]
        t_cur, oi_cur = sorted_oi[i]
        d_oi = oi_cur - oi_prev
        if d_oi <= 0:
            continue
        candle = _candle_at_or_before(candles, t_cur)
        if not candle:
            continue
        entry = _num(candle.get("close")) or mark
        if not entry or entry <= 0:
            continue
        usd_added = d_oi * entry
        for lev, w in LEVERAGE_WEIGHTS:
            slice_usd = usd_added * w
            _add_bin(bins, "long", isolated_liq_long(entry, lev), mark, slice_usd * long_w)
            _add_bin(bins, "short", isolated_liq_short(entry, lev), mark, slice_usd * short_w)
    return bins


def _hist_from_liquidations(
    events: list[dict[str, Any]],
    mark: float,
    now_ms: int | None = None,
) -> dict[tuple[str, float], float]:
    bins: dict[tuple[str, float], float] = {}
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    cutoff = now - HIST_WINDOW_MS
    for ev in events:
        ts = _ts_ms(ev.get("time") or ev.get("timestamp"))
        if ts is not None and ts < cutoff:
            continue
        price = _num(ev.get("price"))
        size = _num(ev.get("size"))
        if not price or not size:
            continue
        notional = price * size
        side_raw = str(ev.get("side") or "")
        pos = ev.get("position")
        if pos == "long" or side_raw == "Buy":
            _add_bin(bins, "long", price, mark, notional)
        elif pos == "short" or side_raw == "Sell":
            _add_bin(bins, "short", price, mark, notional)
    return bins


def _merge_bins(*parts: dict[tuple[str, float], float]) -> dict[tuple[str, float], float]:
    out: dict[tuple[str, float], float] = {}
    for part in parts:
        for key, val in part.items():
            out[key] = out.get(key, 0.0) + val
    return out


def _swept_to_liquidate(
    side: str,
    price: float,
    mark: float,
    candles: list[dict[str, Any]],
    since_ms: int | None = None,
) -> bool:
    """Long — снятие при падении к уровню; short — при росте. Проход снизу вверь не считаем."""
    if side == "long":
        if mark > price * 1.0015:
            return False
        for c in candles:
            t = _ts_ms(c.get("timestamp") or c.get("time"))
            if since_ms is not None and t is not None and t < since_ms:
                continue
            lo = _num(c.get("low"))
            if lo is not None and lo <= price * 1.0015:
                return True
        return False
    if mark < price * 0.9985:
        return False
    for c in candles:
        t = _ts_ms(c.get("timestamp") or c.get("time"))
        if since_ms is not None and t is not None and t < since_ms:
            continue
        hi = _num(c.get("high"))
        if hi is not None and hi >= price * 0.9985:
            return True
    return False


def _split_notional(
    side: str,
    price: float,
    notional: float,
    mark: float,
    hist_bins: dict[tuple[str, float], float],
    model_bins: dict[tuple[str, float], float],
    candles: list[dict[str, Any]] | None,
    now_ms: int | None,
) -> tuple[float, float]:
    """pending (впереди), cleared (уже проходили / факт liq)."""
    key = (side, price)
    hist_n = hist_bins.get(key, 0.0)
    model_n = model_bins.get(key, 0.0)
    cleared = hist_n
    pending = 0.0
    window_start = (now_ms if now_ms is not None else int(time.time() * 1000)) - HIST_WINDOW_MS
    touched = _swept_to_liquidate(side, price, mark, candles or [], since_ms=window_start)
    if model_n > 0:
        if touched:
            cleared += model_n
        else:
            pending += model_n
    anchor_n = notional - hist_n - model_n
    if anchor_n > 1e-6:
        if touched:
            cleared += anchor_n
        else:
            pending += anchor_n
    return pending, cleared


def _anchor_bins_from_mark(mark: float) -> dict[tuple[str, float], float]:
    """Типовые уровни isolated-liq от текущей mark, если нет OI/истории."""
    bins: dict[tuple[str, float], float] = {}
    base = max(mark * 6000.0, 500.0)
    for lev, w in LEVERAGE_WEIGHTS:
        n = base * w
        _add_bin(bins, "long", isolated_liq_long(mark, lev), mark, n)
        _add_bin(bins, "short", isolated_liq_short(mark, lev), mark, n * 0.9)
    return bins


def estimate_liquidation_zones(
    *,
    mark: float,
    oi_rows: list[dict[str, Any]] | None = None,
    candles: list[dict[str, Any]] | None = None,
    liquidations: list[dict[str, Any]] | None = None,
    taker_buy: float = 0.0,
    taker_sell: float = 0.0,
    depth_pct: float = DEFAULT_DEPTH_PCT,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Возвращает зоны long (ниже mark) и short (выше mark) в полосе ±depth_pct."""
    if not mark or mark <= 0:
        return {
            "mark": 0.0,
            "depth_pct": depth_pct,
            "model": True,
            "zones": [],
            "lo": 0.0,
            "hi": 0.0,
        }
    lo = mark * (1.0 - depth_pct)
    hi = mark * (1.0 + depth_pct)
    long_w, short_w = _taker_weights(taker_buy, taker_sell)
    model_bins = _model_from_oi(oi_rows or [], candles or [], mark, long_w, short_w)
    hist_bins = _hist_from_liquidations(liquidations or [], mark, now_ms)
    merged = _merge_bins(model_bins, hist_bins)
    if not merged:
        merged = _anchor_bins_from_mark(mark)

    zones: list[dict[str, Any]] = []
    for (side, price), notional in merged.items():
        if price < lo or price > hi:
            continue
        if side == "long" and price > mark * 1.002:
            continue
        if side == "short" and price < mark * 0.998:
            continue
        src = "mixed"
        if (side, price) in hist_bins and (side, price) not in model_bins:
            src = "hist"
        elif (side, price) in model_bins and (side, price) not in hist_bins:
            src = "model"
        elif not hist_bins and not model_bins:
            src = "model"
        pending, cleared = _split_notional(
            side, price, notional, mark, hist_bins, model_bins, candles, now_ms
        )
        zones.append(
            {
                "price": price,
                "side": side,
                "notional_usd": round(pending + cleared, 2),
                "notional_pending_usd": round(pending, 2),
                "notional_cleared_usd": round(cleared, 2),
                "source": src,
            }
        )

    longs = sorted([z for z in zones if z["side"] == "long"], key=lambda z: z["notional_usd"], reverse=True)[
        :MAX_ZONES_PER_SIDE
    ]
    shorts = sorted([z for z in zones if z["side"] == "short"], key=lambda z: z["notional_usd"], reverse=True)[
        :MAX_ZONES_PER_SIDE
    ]
    out_zones = sorted(longs + shorts, key=lambda z: z["price"])
    return {
        "mark": mark,
        "depth_pct": depth_pct,
        "model": True,
        "lo": lo,
        "hi": hi,
        "zones": out_zones,
    }
