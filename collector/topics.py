"""Топики Bybit и нарезка подписок по соединениям.

Коллектор подписывается на четыре канала каждой пары:
publicTrade, allLiquidation, orderbook.50, tickers.
Устаревший топик liquidation не используется.
"""

from __future__ import annotations

import json

import config


def reconnect_delay(attempt: int) -> int:
    """Пауза перед следующей попыткой: 1, 2, 4, 8 и дальше 8 секунд."""
    if attempt < 0:
        attempt = 0
    index = min(attempt, len(config.RECONNECT_DELAYS_SEC) - 1)
    return config.RECONNECT_DELAYS_SEC[index]


def topics_for_symbol(symbol: str) -> list[str]:
    return [
        config.WS_TOPIC_TRADE.format(symbol=symbol),
        config.WS_TOPIC_LIQUIDATION.format(symbol=symbol),
        config.WS_TOPIC_ORDERBOOK.format(symbol=symbol),
        config.WS_TOPIC_TICKER.format(symbol=symbol),
    ]


def _args_chars(topics: list[str]) -> int:
    """Длина JSON-массива args. Bybit ограничивает её 21 000 символами."""
    if not topics:
        return 2
    return len(json.dumps(topics, separators=(",", ":")))


def shard_symbols(
    symbols: list[str],
    per_connection: int | None = None,
    max_args_chars: int | None = None,
) -> list[list[str]]:
    """Разложить пары по соединениям, не превышая ни число пар, ни длину args."""
    limit = per_connection if per_connection is not None else config.WS_SYMBOLS_PER_CONNECTION
    char_limit = max_args_chars if max_args_chars is not None else config.WS_MAX_ARGS_CHARS
    if limit < 1:
        raise ValueError("per_connection должен быть не меньше 1")
    if char_limit < 1:
        raise ValueError("max_args_chars должен быть не меньше 1")

    groups: list[list[str]] = []
    current: list[str] = []
    current_topics: list[str] = []
    for symbol in symbols:
        extra = topics_for_symbol(symbol)
        candidate = current_topics + extra
        overflow = current and (
            len(current) >= limit or _args_chars(candidate) > char_limit
        )
        if overflow:
            groups.append(current)
            current = []
            current_topics = []
        current.append(symbol)
        current_topics.extend(extra)
    if current:
        groups.append(current)
    return groups


def subscribe_requests(symbols: list[str], batch_size: int | None = None) -> list[dict]:
    """Несколько кадров subscribe. На линейном рынке лимита args нет, пакет всё равно короткий."""
    size = batch_size if batch_size is not None else config.WS_SUBSCRIBE_BATCH
    if size < 1:
        raise ValueError("batch_size должен быть не меньше 1")
    args: list[str] = []
    for symbol in symbols:
        args.extend(topics_for_symbol(symbol))
    requests = []
    for offset in range(0, len(args), size):
        requests.append({"op": "subscribe", "args": args[offset : offset + size]})
    return requests
