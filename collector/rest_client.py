"""REST Bybit через ccxt: список контрактов, OI, свечи и снапшот стакана.

Запросы идут по одному: общий замок не даёт параллельным сокетам
пробить лимит биржи в момент переподключения.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import config
from collector.normalize import kline_message, oi_message, orderbook_from_rest


log = logging.getLogger(__name__)


def is_tracked_contract(item: dict[str, Any]) -> bool:
    """USDT-перпетуал в статусе Trading. Срочные фьючерсы и другие котировки — мимо."""
    return (
        item.get("quoteCoin") == config.BYBIT_QUOTE
        and item.get("contractType") == "LinearPerpetual"
        and item.get("status") == "Trading"
    )


def symbols_from_instruments(payload: dict[str, Any]) -> tuple[list[str], str]:
    """Достать символы и курсор следующей страницы из ответа instruments-info."""
    result = _result(payload)
    symbols = [
        item["symbol"]
        for item in result.get("list") or []
        if isinstance(item, dict) and is_tracked_contract(item) and item.get("symbol")
    ]
    cursor = result.get("nextPageCursor") or ""
    return symbols, str(cursor)


def _result(payload: dict[str, Any]) -> dict[str, Any]:
    code = payload.get("retCode")
    if code not in (0, "0", None):
        raise RuntimeError(str(payload.get("retMsg") or code))
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("В ответе Bybit нет result")
    return result


class BybitRest:
    """Тонкая обёртка над ccxt.async_support.bybit."""

    def __init__(self) -> None:
        self._exchange: Any = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        try:
            import ccxt.async_support as ccxt_async
        except ImportError as exc:
            raise SystemExit(
                "Не установлен пакет ccxt. Выполните: pip install -r requirements.txt"
            ) from exc
        options: dict[str, Any] = {
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        }
        if config.BYBIT_API_KEY and config.BYBIT_API_SECRET:
            options["apiKey"] = config.BYBIT_API_KEY
            options["secret"] = config.BYBIT_API_SECRET
        if config.BYBIT_PROXY:
            options["proxies"] = {
                "http": config.BYBIT_PROXY,
                "https": config.BYBIT_PROXY,
            }
        self._exchange = ccxt_async.bybit(options)
        # Шаблон ccxt — https://api.{hostname}, hostname по умолчанию bybit.com.
        # Подмена hostname на api.bybit.com дала бы хост api.api.bybit.com.
        root = config.BYBIT_REST_URL.rstrip("/")
        if root and root != "https://api.bybit.com":
            api_urls = self._exchange.urls.get("api")
            if isinstance(api_urls, dict):
                for key in list(api_urls):
                    api_urls[key] = root

    async def close(self) -> None:
        if self._exchange is not None:
            await self._exchange.close()
            self._exchange = None

    async def list_usdt_perpetuals(self) -> list[str]:
        """Все торгуемые USDT-перпетуалы, постранично."""
        found: list[str] = []
        cursor = ""
        seen_cursors: set[str] = set()
        while True:
            if cursor:
                if cursor in seen_cursors:
                    break
                seen_cursors.add(cursor)
            params: dict[str, Any] = {"category": config.BYBIT_CATEGORY, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            payload = await self._call("publicGetV5MarketInstrumentsInfo", params)
            page, cursor = symbols_from_instruments(payload)
            found.extend(page)
            if not cursor:
                break
        return sorted(set(found))

    async def fetch_orderbook_snapshot(self, symbol: str) -> dict[str, Any] | None:
        params = {
            "category": config.BYBIT_CATEGORY,
            "symbol": symbol,
            "limit": config.ORDERBOOK_DEPTH,
        }
        payload = await self._call("publicGetV5MarketOrderbook", params)
        return orderbook_from_rest(_result(payload))

    async def fetch_klines(self, symbol: str, interval: str) -> dict[str, Any] | None:
        params = {
            "category": config.BYBIT_CATEGORY,
            "symbol": symbol,
            "interval": interval,
            "limit": config.KLINE_FETCH_LIMIT,
        }
        payload = await self._call("publicGetV5MarketKline", params)
        rows = _result(payload).get("list") or []
        return kline_message(symbol, interval, rows)

    async def fetch_open_interest(self, symbol: str, interval: str) -> dict[str, Any] | None:
        params = {
            "category": config.BYBIT_CATEGORY,
            "symbol": symbol,
            "intervalTime": interval,
            "limit": config.OI_FETCH_LIMIT,
        }
        payload = await self._call("publicGetV5MarketOpenInterest", params)
        rows = _result(payload).get("list") or []
        return oi_message(symbol, interval, rows)

    async def _call(self, method_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._exchange is None:
            raise RuntimeError("REST-клиент не открыт")
        method = getattr(self._exchange, method_name)
        async with self._lock:
            return await method(params)
