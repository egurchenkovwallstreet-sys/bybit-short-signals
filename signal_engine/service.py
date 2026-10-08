"""Подписка на поток коллектора и публикация готовых сигналов.

У Redis соединение в режиме subscribe не умеет publish, поэтому клиентов два.
Буфер канала сигналов тот же: 1024, при переполнении выпадает самое старое.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import config
from collector.publisher import RedisPublisher, open_redis
from signal_engine.engine import Engine
from signal_engine.paper.strategy import PaperStrategy
from signal_engine.store import SignalStore


log = logging.getLogger(__name__)


class SignalService:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or Engine(SignalStore(config.SQLITE_PATH), paper=PaperStrategy())
        self._market = None
        self._publisher_redis = None
        self._publisher: RedisPublisher | None = None

    async def run(self) -> None:
        self.engine.store.open()
        self.engine.restore()
        self._market = await open_redis(config.REDIS_URL)
        self._publisher_redis = await open_redis(config.REDIS_URL)
        self._publisher = RedisPublisher(
            self._publisher_redis,
            config.REDIS_CHANNEL_SIGNALS,
            config.REDIS_CHANNEL_BUFFER,
        )
        await self._publisher.start()
        pubsub = self._market.pubsub()
        await pubsub.subscribe(config.REDIS_CHANNEL_MARKET)
        log.info(
            "Движок слушает %s и пишет в %s",
            config.REDIS_CHANNEL_MARKET,
            config.REDIS_CHANNEL_SIGNALS,
        )
        next_scan = 0.0
        kline_task = (
            asyncio.create_task(self._paper_kline_loop()) if self.engine.paper is not None else None
        )
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    self._ingest_raw(message.get("data"))
                now = time.monotonic()
                if now >= next_scan:
                    for item in self.engine.scan(int(time.time() * 1000)):
                        self._publisher.publish(item)
                    next_scan = now + config.MARKET_SCAN_INTERVAL_SEC
        finally:
            if kline_task is not None:
                kline_task.cancel()
                await asyncio.gather(kline_task, return_exceptions=True)
            if self.engine.paper is not None:
                self.engine.paper.close()
            await pubsub.unsubscribe(config.REDIS_CHANNEL_MARKET)
            await pubsub.aclose()
            if self._publisher is not None:
                await self._publisher.stop()
            for client in (self._market, self._publisher_redis):
                if client is None:
                    continue
                close = getattr(client, "aclose", None) or getattr(client, "close", None)
                if close is not None:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
            self.engine.store.close()
            self.engine.watches.close()

    async def _paper_kline_loop(self) -> None:
        """Свечи 15m/30m/1H/4H с глубиной под EMA200 — только для кандидатов теста."""
        from collector.rest_client import BybitRest

        paper = self.engine.paper
        assert paper is not None
        rest = BybitRest()
        await rest.open()
        try:
            while True:
                for symbol in paper.kline_wanted():
                    fetched = paper.kline_at.get(symbol, 0.0)
                    if time.time() - fetched < config.PAPER_KLINE_REFRESH_SEC:
                        continue
                    for interval in config.PAPER_EMA_INTERVALS:
                        try:
                            message = await rest.fetch_klines(symbol, interval, config.PAPER_KLINE_LIMIT)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            log.exception("Тест: свечи %s %s не получены", symbol, interval)
                            continue
                        candles = ((message or {}).get("data") or {}).get("candles") or []
                        paper.on_klines(symbol, interval, candles)
                await asyncio.sleep(5)
        finally:
            await rest.close()

    def _ingest_raw(self, raw: object) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str):
            return
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Кадр рынка не JSON")
            return
        if isinstance(message, dict):
            self.engine.ingest(message)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(SignalService().run())
    except KeyboardInterrupt:
        log.info("Движок сигналов остановлен")
