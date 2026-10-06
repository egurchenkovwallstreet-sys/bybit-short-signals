"""Нормализация сообщений Bybit в единый конверт перед Redis.

Время в поле timestamp — миллисекунды, как отдаёт Bybit.
Коллектор не фильтрует ликвидации и не считает индикаторы:
сторона S передаётся как есть (Sell — ликвидация шорта, Buy — лонга).

Помимо типов из ТЗ (trade, liquidation, orderbook, ticker) конверт
также несёт open_interest и kline: это ответы REST, без них
движку сигналов нечего читать.
"""

from __future__ import annotations

import logging
from typing import Any


log = logging.getLogger(__name__)

# Поля тикера, которые нужны движку. Остальное Bybit может прислать в дельте.
_TICKER_FIELDS = {
    "lastPrice": ("last_price", float),
    "markPrice": ("mark_price", float),
    "indexPrice": ("index_price", float),
    "fundingRate": ("funding_rate", float),
    "nextFundingTime": ("next_funding_time", int),
    "openInterest": ("open_interest", float),
    "openInterestValue": ("open_interest_value", float),
    "volume24h": ("volume_24h", float),
    "turnover24h": ("turnover_24h", float),
    "price24hPcnt": ("price_24h_change", float),
    "bid1Price": ("bid1_price", float),
    "bid1Size": ("bid1_size", float),
    "ask1Price": ("ask1_price", float),
    "ask1Size": ("ask1_size", float),
}


def envelope(symbol: str, timestamp: int, kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Общий формат сообщения, которое уходит в Redis."""
    return {
        "symbol": symbol,
        "timestamp": int(timestamp),
        "type": kind,
        "data": data,
    }


def messages_from_frame(frame: dict[str, Any]) -> list[dict[str, Any]]:
    """Разобрать один кадр WebSocket. Служебные кадры дают пустой список."""
    if not isinstance(frame, dict):
        return []

    op = frame.get("op")
    if op:
        if frame.get("success") is False:
            log.error("Bybit отклонил %s: %s", op, frame.get("ret_msg"))
        return []

    topic = frame.get("topic")
    if not isinstance(topic, str) or "." not in topic:
        return []

    if topic.startswith("publicTrade."):
        return _trades(frame)
    if topic.startswith("allLiquidation."):
        return _liquidations(frame)
    if topic.startswith("orderbook."):
        book = _orderbook(frame, source="ws")
        return [book] if book else []
    if topic.startswith("tickers."):
        tick = _ticker(frame)
        return [tick] if tick else []
    return []


def _symbol_from_topic(topic: str) -> str:
    return topic.rsplit(".", 1)[-1]


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _trades(frame: dict[str, Any]) -> list[dict[str, Any]]:
    topic = frame["topic"]
    fallback_symbol = _symbol_from_topic(topic)
    fallback_ts = _to_int(frame.get("ts")) or 0
    events: list[dict[str, Any]] = []
    rows = frame.get("data") or []
    if isinstance(rows, dict):
        rows = [rows]
    for row in rows:
        if not isinstance(row, dict):
            continue
        price = _to_float(row.get("p"))
        size = _to_float(row.get("v"))
        if price is None or size is None:
            continue
        symbol = str(row.get("s") or fallback_symbol)
        timestamp = _to_int(row.get("T")) or fallback_ts
        events.append(
            envelope(
                symbol,
                timestamp,
                "trade",
                {
                    "price": price,
                    "size": size,
                    "side": row.get("S"),
                    "trade_id": row.get("i"),
                    "is_block_trade": bool(row.get("BT", False)),
                },
            )
        )
    return events


def _liquidations(frame: dict[str, Any]) -> list[dict[str, Any]]:
    """S = Sell — ликвидирован шорт, S = Buy — ликвидирован лонг."""
    fallback_symbol = _symbol_from_topic(frame["topic"])
    fallback_ts = _to_int(frame.get("ts")) or 0
    events: list[dict[str, Any]] = []
    rows = frame.get("data") or []
    if isinstance(rows, dict):
        rows = [rows]
    for row in rows:
        if not isinstance(row, dict):
            continue
        price = _to_float(row.get("p"))
        size = _to_float(row.get("v"))
        if price is None or size is None:
            continue
        symbol = str(row.get("s") or fallback_symbol)
        timestamp = _to_int(row.get("T")) or fallback_ts
        events.append(
            envelope(
                symbol,
                timestamp,
                "liquidation",
                {
                    "side": row.get("S"),
                    "price": price,
                    "size": size,
                },
            )
        )
    return events


def _levels(rows: Any) -> list[list[float]]:
    levels: list[list[float]] = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price = _to_float(row[0])
        size = _to_float(row[1])
        if price is None or size is None:
            continue
        # size = 0 в дельте означает: уровень снят.
        levels.append([price, size])
    return levels


def _orderbook(frame: dict[str, Any], source: str) -> dict[str, Any] | None:
    data = frame.get("data")
    if not isinstance(data, dict):
        return None
    topic = str(frame.get("topic") or "")
    symbol = str(data.get("s") or _symbol_from_topic(topic))
    timestamp = _to_int(frame.get("ts")) or _to_int(data.get("ts")) or 0
    kind = frame.get("type") or "snapshot"
    update_id = _to_int(data.get("u"))
    # u = 1 Bybit присылает, когда книгу нужно перезаписать целиком.
    reset = kind == "snapshot" or update_id == 1
    return envelope(
        symbol,
        timestamp,
        "orderbook",
        {
            "source": source,
            "kind": kind,
            "reset": reset,
            "bids": _levels(data.get("b")),
            "asks": _levels(data.get("a")),
            "update_id": update_id,
        },
    )


def orderbook_from_rest(result: dict[str, Any]) -> dict[str, Any] | None:
    """Снапшот стакана из GET /v5/market/orderbook после переподключения."""
    if not isinstance(result, dict):
        return None
    frame = {
        "topic": f"orderbook.50.{result.get('s', '')}",
        "type": "snapshot",
        "ts": result.get("ts"),
        "data": result,
    }
    return _orderbook(frame, source="rest")


def _ticker(frame: dict[str, Any]) -> dict[str, Any] | None:
    data = frame.get("data")
    if not isinstance(data, dict):
        return None
    symbol = str(data.get("symbol") or _symbol_from_topic(frame["topic"]))
    timestamp = _to_int(frame.get("ts")) or 0
    payload: dict[str, Any] = {
        "partial": frame.get("type") != "snapshot",
    }
    for source_key, (target_key, caster) in _TICKER_FIELDS.items():
        if source_key not in data:
            continue
        raw = data.get(source_key)
        if raw is None or raw == "":
            continue
        try:
            payload[target_key] = caster(raw)
        except (TypeError, ValueError):
            continue
    return envelope(symbol, timestamp, "ticker", payload)


def parse_kline_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """Свечи Bybit приходят от новых к старым. Наружу отдаём по возрастанию времени."""
    candles: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        timestamp = _to_int(row[0])
        open_ = _to_float(row[1])
        high = _to_float(row[2])
        low = _to_float(row[3])
        close = _to_float(row[4])
        volume = _to_float(row[5])
        if None in (timestamp, open_, high, low, close, volume):
            continue
        candle: dict[str, Any] = {
            "timestamp": timestamp,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
        if len(row) > 6:
            turnover = _to_float(row[6])
            if turnover is not None:
                candle["turnover"] = turnover
        candles.append(candle)
    candles.sort(key=lambda item: item["timestamp"])
    return candles


def kline_message(symbol: str, interval: str, rows: list[Any]) -> dict[str, Any] | None:
    candles = parse_kline_rows(rows)
    if not candles:
        return None
    return envelope(
        symbol,
        candles[-1]["timestamp"],
        "kline",
        {"interval": interval, "candles": candles},
    )


def parse_oi_rows(rows: list[Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row in rows or []:
        timestamp: int | None = None
        value: float | None = None
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            timestamp = _to_int(row[0])
            value = _to_float(row[1])
        elif isinstance(row, dict):
            timestamp = _to_int(row.get("timestamp") or row.get("time"))
            value = _to_float(row.get("openInterest") or row.get("open_interest"))
        if timestamp is None or value is None:
            continue
        points.append({"timestamp": timestamp, "open_interest": value})
    points.sort(key=lambda item: item["timestamp"])
    return points


def oi_message(symbol: str, interval: str, rows: list[Any]) -> dict[str, Any] | None:
    points = parse_oi_rows(rows)
    if not points:
        return None
    return envelope(
        symbol,
        points[-1]["timestamp"],
        "open_interest",
        {"interval": interval, "points": points},
    )
