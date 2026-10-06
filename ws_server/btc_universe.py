"""Список пар с оценкой волатильности для вкладки теста стратегии."""

from __future__ import annotations

from typing import Any

import config
from strategy_test.volatility import volatility_pct_24h
from ws_server.cache import MarketCache


def list_symbols_with_volatility(cache: MarketCache, limit: int = 80) -> list[dict[str, Any]]:
    by_sym: dict[str, float | None] = {}

    for (symbol, interval), candles in cache.klines.items():
        if interval != "60" or not candles:
            continue
        vol = volatility_pct_24h(candles)
        if vol is None:
            continue
        prev = by_sym.get(symbol)
        if prev is None or vol > prev:
            by_sym[symbol] = vol

    for symbol in cache.signals:
        by_sym.setdefault(symbol, None)
        if by_sym[symbol] is not None:
            continue
        candles = cache.klines.get((symbol, "60"), [])
        if candles:
            by_sym[symbol] = volatility_pct_24h(candles)

    by_sym.setdefault(config.BTC_TEST_SYMBOL, None)
    if by_sym[config.BTC_TEST_SYMBOL] is None:
        candles = cache.klines.get((config.BTC_TEST_SYMBOL, "60"), [])
        if candles:
            by_sym[config.BTC_TEST_SYMBOL] = volatility_pct_24h(candles)

    rows = [
        {"symbol": sym, "volatility_pct": vol if vol is not None else 0.0}
        for sym, vol in by_sym.items()
        if sym.endswith("USDT")
    ]
    rows.sort(key=lambda item: item["volatility_pct"], reverse=True)
    return rows[:limit]
