"""Сборка коллектора: список пар, сокеты, REST-опрос, публикация в Redis.

Проверка пампа каждые 3 секунды здесь не делается.
Коллектор только приносит данные. Условия пампа считает signal_engine.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import config
from collector.publisher import RedisPublisher, open_redis
from collector.rest_client import BybitRest
from collector.topics import shard_symbols
from collector.ws_client import BybitWsClient


log = logging.getLogger(__name__)


class SymbolUniverse:
    """Текущий список пар. Смена списка будит супервизор сокетов."""

    def __init__(self) -> None:
        self.symbols: list[str] = []
        self.changed = asyncio.Event()

    def replace(self, symbols: list[str]) -> bool:
        ordered = list(symbols)
        if ordered == self.symbols:
            return False
        self.symbols = ordered
        self.changed.set()
        return True


class CollectorService:
    def __init__(
        self,
        rest: BybitRest | None = None,
        publisher: RedisPublisher | None = None,
        redis_client: Any = None,
    ) -> None:
        self.rest = rest or BybitRest()
        self.publisher = publisher
        self._redis = redis_client
        self.universe = SymbolUniverse()
        self._owns_rest = rest is None
        self._owns_redis = redis_client is None

    async def run(self) -> None:
        if self.publisher is None:
            self._redis = await open_redis(config.REDIS_URL)
            self.publisher = RedisPublisher(
                self._redis,
                config.REDIS_CHANNEL_MARKET,
                config.REDIS_CHANNEL_BUFFER,
            )
        assert self.publisher is not None
        try:
            if self._owns_rest:
                await self.rest.open()
            await self.publisher.start()
            await self._refresh_symbols()
            await asyncio.gather(
                self._supervise_sockets(),
                self._refresh_loop(),
                self._rest_loop(),
            )
        finally:
            if self.publisher is not None:
                await self.publisher.stop()
            if self._owns_rest:
                await self.rest.close()
            if self._owns_redis and self._redis is not None:
                close = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)
                if close is not None:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result

    async def _refresh_symbols(self) -> None:
        symbols = await self.rest.list_usdt_perpetuals()
        changed = self.universe.replace(symbols)
        log.info(
            "Пар в мониторинге: %s%s",
            len(symbols),
            ", список обновлён" if changed else "",
        )

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(config.INSTRUMENTS_REFRESH_SEC)
            try:
                await self._refresh_symbols()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Не удалось обновить список контрактов")

    async def _supervise_sockets(self) -> None:
        tasks: list[asyncio.Task] = []
        seen: list[str] | None = None
        try:
            while True:
                current = list(self.universe.symbols)
                if current != seen:
                    await _cancel(tasks)
                    seen = current
                    tasks = self._spawn(current)
                try:
                    await asyncio.wait_for(self.universe.changed.wait(), timeout=1)
                except TimeoutError:
                    pass
                self.universe.changed.clear()
        finally:
            await _cancel(tasks)

    def _spawn(self, symbols: list[str]) -> list[asyncio.Task]:
        if not symbols:
            log.warning("Список пар пуст, сокеты не открыты")
            return []
        groups = shard_symbols(symbols)
        log.info("WebSocket-соединений: %s", len(groups))
        tasks = []
        for index, group in enumerate(groups):
            client = BybitWsClient(
                config.BYBIT_WS_PUBLIC_LINEAR,
                group,
                on_messages=self._on_messages,
                on_connected=self._on_connected,
                name=f"ws-{index}",
            )
            tasks.append(asyncio.create_task(client.run(), name=f"ws-{index}"))
        return tasks

    async def _on_messages(self, messages: list[dict[str, Any]]) -> None:
        assert self.publisher is not None
        for message in messages:
            self.publisher.publish(message)

    async def _on_connected(self, symbols: list[str]) -> None:
        """Снапшот стакана, чтобы после разрыва книга не собиралась из одних дельт."""
        assert self.publisher is not None
        for symbol in symbols:
            try:
                snapshot = await self.rest.fetch_orderbook_snapshot(symbol)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Снапшот стакана %s не получен", symbol)
                continue
            if snapshot is not None:
                self.publisher.publish(snapshot)

    async def _rest_loop(self) -> None:
        """Круг OI и свечей по всем парам. Ошибки одной пары не останавливают круг."""
        while True:
            symbols = list(self.universe.symbols)
            for symbol in symbols:
                for interval in config.OI_INTERVALS:
                    await self._publish_rest(self.rest.fetch_open_interest(symbol, interval))
                for interval in config.KLINE_INTERVALS:
                    await self._publish_rest(self.rest.fetch_klines(symbol, interval))
            await asyncio.sleep(config.REST_CYCLE_PAUSE_SEC)

    async def _publish_rest(self, awaitable: Any) -> None:
        assert self.publisher is not None
        try:
            message = await awaitable
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("REST-запрос не выполнен")
            return
        if message is not None:
            self.publisher.publish(message)


async def _cancel(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(CollectorService().run())
    except KeyboardInterrupt:
        log.info("Коллектор остановлен")
