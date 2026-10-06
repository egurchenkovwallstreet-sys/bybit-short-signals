"""Актив теста стратегии (общий ключ Redis для ws-server и strategy_test)."""

from __future__ import annotations

from typing import Any

import config


async def read_active_symbol(redis: Any) -> str:
    raw = await redis.get(config.BTC_TEST_SYMBOL_REDIS_KEY)
    sym = (raw or config.BTC_TEST_SYMBOL or "BTCUSDT").strip().upper()
    return sym


async def write_active_symbol(redis: Any, symbol: str) -> str:
    sym = symbol.strip().upper()
    await redis.set(config.BTC_TEST_SYMBOL_REDIS_KEY, sym)
    return sym
