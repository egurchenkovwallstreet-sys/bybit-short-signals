"""Скан отрыва EMA60 по REST (если в Redis мало 5m-баров)."""

from __future__ import annotations

import logging
from typing import Any

import config
from signal_engine.indicators import ema

log = logging.getLogger(__name__)


def scan_top_stretches(
    http: Any,
    *,
    symbol_limit: int = 80,
    min_turnover_usdt: float | None = None,
) -> list[tuple[str, str, float, float, float]]:
    """(symbol, side, stretch_pct, ema60, last_price) отсортировано по stretch."""
    floor = config.EM6_BYBIT_STRETCH_FLOOR_PCT
    min_turn = min_turnover_usdt
    if min_turn is None:
        min_turn = float(config.ema60_stretch_min_turnover_usdt(config.PAPER_EM6R_VARIANT) or 0)
    try:
        tickers = (http.get_tickers(category="linear").get("result") or {}).get("list") or []
    except Exception:
        log.exception("em6 bybit: get_tickers")
        return []
    ranked: list[tuple[float, str]] = []
    for t in tickers:
        sym = str(t.get("symbol") or "")
        if not sym.endswith("USDT"):
            continue
        turn = float(t.get("turnover24h") or 0)
        if min_turn > 0 and turn + 1e-9 < min_turn:
            continue
        ranked.append((turn, sym))
    ranked.sort(reverse=True)
    out: list[tuple[str, str, float, float, float]] = []
    for _, sym in ranked[:symbol_limit]:
        try:
            resp = http.get_kline(category="linear", symbol=sym, interval="5", limit=200)
        except Exception:
            continue
        rows = (resp.get("result") or {}).get("list") or []
        if len(rows) < 65:
            continue
        closes = [float(r[4]) for r in reversed(rows)]
        ema60 = ema(closes, 60)
        if ema60[-1] is None:
            continue
        e = float(ema60[-1])
        price = closes[-1]
        stretch = abs(price - e) / e * 100.0
        if stretch + 1e-9 < floor:
            continue
        side = "long" if price < e else "short"
        out.append((sym, side, stretch, e, price))
    out.sort(key=lambda x: x[2], reverse=True)
    return out
