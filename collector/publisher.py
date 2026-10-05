"""Публикация нормализованных сообщений в Redis Pub/Sub."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from collector.buffer import DropOldestQueue


log = logging.getLogger(__name__)


class RedisPublisher:
    """Кладёт сообщения в ограниченный буфер и публикует их в один канал."""

    def __init__(self, redis_client: Any, channel: str, maxsize: int) -> None:
        self._redis = redis_client
        self.channel = channel
        self.queue: DropOldestQueue[dict[str, Any]] = DropOldestQueue(maxsize)
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._last_logged_drop = 0

    def publish(self, message: dict[str, Any]) -> None:
        """Поставить сообщение в буфер. При переполнении выпадает самое старое."""
        self.queue.put(message)
        dropped = self.queue.dropped
        if dropped != self._last_logged_drop and (dropped == 1 or dropped % 1000 == 0):
            self._last_logged_drop = dropped
            log.warning(
                "Буфер канала %s переполнен, отброшено старых сообщений: %s",
                self.channel,
                dropped,
            )

    async def start(self) -> None:
        if self._task is None:
            self._stopping = False
            self._task = asyncio.create_task(self._loop(), name="redis-publisher")

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stopping:
            message = await self.queue.get()
            payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
            while not self._stopping:
                try:
                    await self._redis.publish(self.channel, payload)
                    break
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("Не удалось опубликовать в Redis, повтор через 1 с")
                    await asyncio.sleep(1)


async def open_redis(url: str) -> Any:
    """Открыть asyncio-клиент redis-py. Импорт здесь, чтобы тесты буфера жили без пакета."""
    try:
        import redis.asyncio as redis_async
    except ImportError as exc:
        raise SystemExit(
            "Не установлен пакет redis. Выполните: pip install -r requirements.txt"
        ) from exc
    return redis_async.from_url(url, decode_responses=True)
