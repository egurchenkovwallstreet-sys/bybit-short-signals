"""Одно публичное WebSocket-соединение Bybit и его переподключение.

После каждого успешного connect вызывается on_connected: снаружи
оттуда запрашивается REST-снапшот стакана, затем сокет подписывается
на потоки. Bybit в ответ на subscribe сам присылает snapshot стакана
и тикера.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

import config
from collector.normalize import messages_from_frame
from collector.topics import reconnect_delay, subscribe_requests


log = logging.getLogger(__name__)

OnMessages = Callable[[list[dict[str, Any]]], Awaitable[None]]
OnConnected = Callable[[list[str]], Awaitable[None]]


class BybitWsClient:
    """Держит подписку набора пар, пока задачу не отменят."""

    def __init__(
        self,
        url: str,
        symbols: list[str],
        on_messages: OnMessages,
        on_connected: OnConnected | None = None,
        name: str = "ws",
        connect: Callable[[], Any] | None = None,
        ping_interval: float | None = None,
    ) -> None:
        self.url = url
        self.symbols = list(symbols)
        self.name = name
        self._on_messages = on_messages
        self._on_connected = on_connected
        self._connect = connect
        if ping_interval is None:
            ping_interval = float(config.WS_PING_INTERVAL_SEC)
        self._ping_interval = ping_interval

    async def run(self) -> None:
        attempt = 0
        while True:
            started = time.monotonic()
            connected = False
            try:
                async with self._open() as ws:
                    connected = True
                    await self._session(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("%s: соединение потеряно (%s)", self.name, exc)
            alive = time.monotonic() - started if connected else 0
            if alive >= config.RECONNECT_RESET_AFTER_SEC:
                attempt = 0
            delay = reconnect_delay(attempt)
            attempt += 1
            log.info("%s: повторное подключение через %s с", self.name, delay)
            await asyncio.sleep(delay)

    def _open(self) -> Any:
        if self._connect is not None:
            return self._connect()
        try:
            import websockets
        except ImportError as exc:
            raise SystemExit(
                "Не установлен пакет websockets. Выполните: pip install -r requirements.txt"
            ) from exc
        # Свой ping Bybit (op=ping). Протокольный ping библиотеки выключен.
        ws_proxy = config.BYBIT_PROXY or None
        return websockets.connect(
            self.url,
            ping_interval=None,
            open_timeout=20,
            max_queue=config.REDIS_CHANNEL_BUFFER,
            # Системный HTTP_PROXY не используем — только BYBIT_PROXY из .env.
            proxy=ws_proxy,
        )

    async def _session(self, ws: Any) -> None:
        # Ping стартует сразу, чтение не ждёт REST. Иначе десятки снапшотов
        # на одном замке держат сокет без ping, и Bybit его рвёт.
        ping_task = None
        snapshot_task = None
        if self._ping_interval and self._ping_interval > 0:
            ping_task = asyncio.create_task(self._ping(ws), name=f"{self.name}-ping")
        await self._subscribe(ws)
        if self._on_connected is not None:
            snapshot_task = asyncio.create_task(
                self._request_snapshot(),
                name=f"{self.name}-snapshot",
            )
        try:
            async for raw in ws:
                await self._handle_raw(raw)
        finally:
            for task in (ping_task, snapshot_task):
                if task is not None:
                    task.cancel()
            for task in (ping_task, snapshot_task):
                if task is None:
                    continue
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _request_snapshot(self) -> None:
        assert self._on_connected is not None
        try:
            await self._on_connected(self.symbols)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s: снапшот после подключения не получен", self.name)

    async def _subscribe(self, ws: Any) -> None:
        requests = subscribe_requests(self.symbols)
        for payload in requests:
            await ws.send(json.dumps(payload, separators=(",", ":")))
        log.info(
            "%s: подписка на %s пар, кадров subscribe: %s",
            self.name,
            len(self.symbols),
            len(requests),
        )

    async def _ping(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(self._ping_interval)
            await ws.send(json.dumps({"op": "ping"}))

    async def _handle_raw(self, raw: Any) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("%s: кадр не JSON", self.name)
            return
        messages = messages_from_frame(frame)
        if messages:
            await self._on_messages(messages)
