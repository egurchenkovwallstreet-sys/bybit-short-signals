"""REST Bybit через ccxt: список контрактов, OI, свечи и снапшот стакана.

Запросы идут по одному: общий замок не даёт параллельным сокетам
пробить лимит биржи в момент переподключения.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import config
from collector.normalize import envelope, kline_message, oi_message, orderbook_from_rest, parse_kline_rows, parse_oi_rows
from collector.symbol_filter import filter_universe


log = logging.getLogger(__name__)


def _merge_series(rows: list[dict[str, Any]], chunk: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    by_key = {row[key]: row for row in rows}
    for row in chunk:
        by_key[row[key]] = row
    return [by_key[k] for k in sorted(by_key)]


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
        """USDT-перпетуалы после фильтра universe (объём, возраст, innovation, delist)."""
        instruments = await self.fetch_linear_instruments()
        turnover = await self.fetch_turnover_24h_by_symbol()
        symbols, stats = filter_universe(instruments, turnover, now_ms=int(time.time() * 1000))
        log.info(
            "Universe: %s из %s linear записей | innovation=%s delist=%s молодые=%s объём<%s=%s статус=%s",
            stats.kept,
            stats.raw,
            stats.skipped_innovation,
            stats.skipped_delisting,
            stats.skipped_too_young,
            int(config.UNIVERSE_MIN_TURNOVER_24H_USDT),
            stats.skipped_low_volume,
            stats.skipped_status,
        )
        return symbols

    async def fetch_linear_instruments(self) -> list[dict[str, Any]]:
        """Все инструменты category=linear, постранично (сырой list из API)."""
        found: list[dict[str, Any]] = []
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
            result = _result(payload)
            batch = result.get("list") or []
            if isinstance(batch, list):
                for item in batch:
                    if isinstance(item, dict):
                        found.append(item)
            cursor = str(result.get("nextPageCursor") or "")
            if not cursor:
                break
        return found

    async def fetch_turnover_24h_by_symbol(self) -> dict[str, float]:
        """turnover24h в USDT по всем linear тикерам."""
        payload = await self._call(
            "publicGetV5MarketTickers",
            {"category": config.BYBIT_CATEGORY},
        )
        rows = _result(payload).get("list") or []
        out: dict[str, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = row.get("symbol")
            if not symbol:
                continue
            try:
                out[str(symbol)] = float(row.get("turnover24h") or 0)
            except (TypeError, ValueError):
                out[str(symbol)] = 0.0
        return out

    async def fetch_orderbook_snapshot(self, symbol: str) -> dict[str, Any] | None:
        params = {
            "category": config.BYBIT_CATEGORY,
            "symbol": symbol,
            "limit": config.ORDERBOOK_DEPTH,
        }
        payload = await self._call("publicGetV5MarketOrderbook", params)
        return orderbook_from_rest(_result(payload))

    async def fetch_klines(self, symbol: str, interval: str, limit: int | None = None) -> dict[str, Any] | None:
        params = {
            "category": config.BYBIT_CATEGORY,
            "symbol": symbol,
            "interval": interval,
            "limit": limit or config.KLINE_FETCH_LIMIT,
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

    async def fetch_klines_for_days(
        self,
        symbol: str,
        interval: str,
        days: int | None = None,
    ) -> dict[str, Any] | None:
        span = days if days is not None else config.PUMP_SCAN_CHART_FETCH_DAYS
        needed = config.kline_bars_for_days(interval, span)
        cutoff_ms = int(time.time() * 1000) - span * 86_400_000
        merged: list[dict[str, Any]] = []
        end: int | None = None
        max_batch = config.BYBIT_KLINE_MAX_LIMIT
        while len(merged) < needed:
            batch_limit = min(max_batch, needed - len(merged))
            params: dict[str, Any] = {
                "category": config.BYBIT_CATEGORY,
                "symbol": symbol,
                "interval": interval,
                "limit": batch_limit,
            }
            if end is not None:
                params["end"] = end
            payload = await self._call("publicGetV5MarketKline", params)
            rows = _result(payload).get("list") or []
            if not rows:
                break
            chunk = parse_kline_rows(rows)
            if not chunk:
                break
            merged = _merge_series(merged, chunk, "timestamp")
            oldest = chunk[0]["timestamp"]
            if oldest <= cutoff_ms:
                break
            end = oldest - 1
            if len(rows) < batch_limit:
                break
        merged = [row for row in merged if row["timestamp"] >= cutoff_ms]
        if not merged:
            return None
        return envelope(
            symbol,
            merged[-1]["timestamp"],
            "kline",
            {"interval": interval, "candles": merged},
        )

    async def fetch_open_interest_for_days(
        self,
        symbol: str,
        interval: str,
        days: int | None = None,
    ) -> dict[str, Any] | None:
        span = days if days is not None else config.PUMP_SCAN_CHART_FETCH_DAYS
        needed = config.oi_bars_for_days(interval, span)
        cutoff_ms = int(time.time() * 1000) - span * 86_400_000
        merged: list[dict[str, Any]] = []
        end: int | None = None
        max_batch = config.BYBIT_KLINE_MAX_LIMIT
        while len(merged) < needed:
            batch_limit = min(max_batch, needed - len(merged))
            params: dict[str, Any] = {
                "category": config.BYBIT_CATEGORY,
                "symbol": symbol,
                "intervalTime": interval,
                "limit": batch_limit,
            }
            if end is not None:
                params["end"] = end
            payload = await self._call("publicGetV5MarketOpenInterest", params)
            rows = _result(payload).get("list") or []
            if not rows:
                break
            chunk = parse_oi_rows(rows)
            if not chunk:
                break
            merged = _merge_series(merged, chunk, "timestamp")
            oldest = chunk[0]["timestamp"]
            if oldest <= cutoff_ms:
                break
            end = oldest - 1
            if len(rows) < batch_limit:
                break
        merged = [row for row in merged if row["timestamp"] >= cutoff_ms]
        if not merged:
            return None
        return envelope(
            symbol,
            merged[-1]["timestamp"],
            "open_interest",
            {"interval": interval, "points": merged},
        )

    async def _call(self, method_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._exchange is None:
            raise RuntimeError("REST-клиент не открыт")
        method = getattr(self._exchange, method_name)
        async with self._lock:
            return await method(params)
