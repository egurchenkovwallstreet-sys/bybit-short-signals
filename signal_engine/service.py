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
from signal_engine.live.em6_bybit.strategy import Em6BybitStrategy
from signal_engine.paper.pivot_clock import batch_has_closed_bar
from signal_engine.paper.strategy import PaperStrategy
from signal_engine.store import SignalStore


log = logging.getLogger(__name__)


class SignalService:
    def __init__(self, engine: Engine | None = None) -> None:
        em6b = Em6BybitStrategy() if config.em6_bybit_enabled() else None
        self.engine = engine or Engine(
            SignalStore(config.SQLITE_PATH),
            paper=PaperStrategy(),
            em6_bybit=em6b,
        )
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
        next_boards = 0.0
        self._confirm_burst = False
        side_tasks: list[asyncio.Task] = []
        if self.engine.paper is not None:
            side_tasks.append(asyncio.create_task(self._paper_kline_loop()))
            side_tasks.append(asyncio.create_task(self._pivot_confirm_loop()))
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    self._ingest_raw(message.get("data"))
                now = time.monotonic()
                if now >= next_scan:
                    ts = int(time.time() * 1000)
                    boards = now >= next_boards and not self._confirm_burst
                    pivots = (ts % 300_000) <= config.PAPER_PIVOT_EVAL_WINDOW_MS
                    paper = self.engine.paper
                    if paper is not None:
                        from signal_engine.state import SymbolState

                        for sym in paper.bab_open_symbols():
                            self.engine.symbols.setdefault(sym, SymbolState(sym))
                        paper.process_bab_opposite_exits(self.engine.symbols, ts)
                    if not self._confirm_burst:
                        for item in self.engine.scan(ts, boards=boards, pivots=pivots):
                            self._publisher.publish(item)
                    next_scan = now + config.MARKET_SCAN_INTERVAL_SEC
                    if boards:
                        next_boards = now + config.PUMP_BOARD_INTERVAL_SEC
        finally:
            for task in side_tasks:
                task.cancel()
            if side_tasks:
                await asyncio.gather(*side_tasks, return_exceptions=True)
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

    def _five_min_symbols(self) -> set[str]:
        """Монеты с оборотом порога LH — им обязательно нужны 5м для баблососа / пылесоса 5."""
        floor = config.VACUUM_LH_MIN_TURNOVER_24H_USDT
        out: set[str] = set()
        for symbol, state in self.engine.symbols.items():
            if not state.last_price:
                continue
            turn = state.turnover_24h_usdt
            if turn is None or float(turn) < floor:
                continue
            out.add(symbol)
        return out

    async def _paper_kline_loop(self) -> None:
        """Свечи теста + 5м в состояние движка для баблососа и пылесоса 5."""
        from collector.rest_client import BybitRest

        paper = self.engine.paper
        assert paper is not None
        rest = BybitRest()
        await rest.open()
        five_at: dict[str, float] = {}
        try:
            while True:
                paper_syms = set(paper.kline_wanted())
                five_syms = self._five_min_symbols() - paper_syms
                for symbol in sorted(paper_syms | five_syms):
                    if self._confirm_burst:
                        await asyncio.sleep(0.2)
                        break
                    if symbol in paper_syms:
                        if time.time() - paper.kline_at.get(symbol, 0.0) < config.PAPER_KLINE_REFRESH_SEC:
                            continue
                        intervals = (*config.PAPER_EMA_INTERVALS, "5")
                        limit = config.PAPER_KLINE_LIMIT
                    else:
                        if time.time() - five_at.get(symbol, 0.0) < config.PAPER_FIVE_MIN_REFRESH_SEC:
                            continue
                        five_at[symbol] = time.time()
                        intervals = ("5",)
                        limit = config.PAPER_FIVE_MIN_FETCH_LIMIT
                    for interval in intervals:
                        try:
                            message = await rest.fetch_klines(symbol, interval, limit)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            log.exception("Тест: свечи %s %s не получены", symbol, interval)
                            continue
                        if not message:
                            continue
                        self.engine.ingest(message)
                        candles = ((message.get("data") or {}).get("candles") or [])
                        paper.on_klines(symbol, interval, candles)
                await asyncio.sleep(5)
        finally:
            await rest.close()

    async def _pivot_confirm_loop(self) -> None:
        """В момент закрытия 5м добирает свечи списка ожидания и сразу сканирует."""
        from collector.rest_client import BybitRest

        paper = self.engine.paper
        assert paper is not None
        rest = BybitRest()
        await rest.open()
        limit = config.PAPER_PIVOT_CONFIRM_FETCH_LIMIT
        parallel = max(1, config.PAPER_PIVOT_CONFIRM_PARALLEL)
        try:
            while True:
                await self._sleep_until_five_min_close(0.6)
                started = time.time()
                close_ms = int(started) // 300 * 300 * 1000
                symbols = paper.confirm_fetch_symbols()
                symbols_15 = paper.confirm_fetch_symbols_15() if close_ms % 900_000 == 0 else []
                if not symbols and not symbols_15:
                    continue
                self._confirm_burst = True
                try:
                    jobs = []
                    if symbols:
                        jobs.append(self._confirm_interval(rest, symbols, "5", close_ms, started, limit, parallel))
                    if symbols_15:
                        jobs.append(
                            self._confirm_interval(rest, symbols_15, "15", close_ms, started, limit, parallel)
                        )
                    await asyncio.gather(*jobs)
                finally:
                    self._confirm_burst = False
        finally:
            await rest.close()

    async def _sleep_until_five_min_close(self, after_sec: float) -> None:
        now = time.time()
        into = now % 300
        if into <= after_sec + 1.0:
            await asyncio.sleep(max(0.0, after_sec - into))
            return
        await asyncio.sleep(300 - into + after_sec)

    async def _confirm_interval(self, rest, symbols: list[str], interval: str, close_ms: int, started: float, limit: int, parallel: int) -> None:
        step = 900_000 if interval == "15" else 300_000
        pending = list(symbols)
        try:
            for pause in (0.0, 1.4, 2.2):
                if pause:
                    await asyncio.sleep(pause)
                if not pending or time.time() - started > 8:
                    break
                fetched = await self._fetch_kline_tail(rest, pending, interval, limit, parallel)
                still: list[str] = []
                ready = 0
                now_ms = int(time.time() * 1000)
                for symbol in pending:
                    message = fetched.get(symbol)
                    candles = ((message or {}).get("data") or {}).get("candles") or []
                    if message and batch_has_closed_bar(candles, close_ms, now_ms, step):
                        self.engine.ingest(message)
                        ready += 1
                    else:
                        still.append(symbol)
                pending = still
                if ready:
                    for item in self.engine.scan(now_ms, boards=False, pivots=True):
                        if self._publisher is not None:
                            self._publisher.publish(item)
        finally:
            lag_ms = int((time.time() - (close_ms / 1000)) * 1000)
            log.info(
                "Пивот %sм: проверка %s монет, осталось без закрытой свечи %s, %d мс после закрытия",
                interval,
                len(symbols),
                len(pending),
                lag_ms,
            )

    async def _fetch_kline_tail(self, rest, symbols: list[str], interval: str, limit: int, parallel: int) -> dict:
        sem = asyncio.Semaphore(parallel)

        async def one(symbol: str):
            async with sem:
                try:
                    return symbol, await rest.fetch_klines(symbol, interval, limit, locked=False)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("Подтверждение %sм %s не получено", interval, symbol)
                    return symbol, None

        pairs = await asyncio.gather(*(one(symbol) for symbol in symbols))
        return {symbol: message for symbol, message in pairs}

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
