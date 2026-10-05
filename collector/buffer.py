"""Очередь с вытеснением самых старых сообщений.

Redis Pub/Sub сам буфер не держит: если подписчик не успевает,
сообщение пропадает. Лимит 1024 стоит на стороне издателя,
чтобы при заторе не копить память без границы.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Generic, TypeVar


T = TypeVar("T")


class DropOldestQueue(Generic[T]):
    """Один потребитель. put можно звать из разных задач."""

    def __init__(self, maxsize: int) -> None:
        if maxsize < 1:
            raise ValueError("maxsize должен быть не меньше 1")
        self.maxsize = maxsize
        self.dropped = 0
        self._items: deque[T] = deque()
        self._waiter: asyncio.Future | None = None

    def __len__(self) -> int:
        return len(self._items)

    def put(self, item: T) -> None:
        if len(self._items) >= self.maxsize:
            self._items.popleft()
            self.dropped += 1
        self._items.append(item)
        waiter = self._waiter
        if waiter is not None and not waiter.done():
            waiter.set_result(None)

    async def get(self) -> T:
        while not self._items:
            loop = asyncio.get_running_loop()
            self._waiter = loop.create_future()
            if self._items:
                self._waiter.cancel()
                self._waiter = None
                break
            await self._waiter
            self._waiter = None
        return self._items.popleft()
