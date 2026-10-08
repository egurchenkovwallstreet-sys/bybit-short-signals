"""Раздача снимков в браузер не чаще 10 Гц. Тикеры пакуются раз в 500 мс.

Пока Redis молчит, на странице пример. Живая доска его заменяет.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import config
from ws_server.cache import MarketCache
from ws_server.paper import PaperCache
from ws_server.demo import demo_board, demo_market, demo_stats
from ws_server.stats import compute_stats


log = logging.getLogger(__name__)


class Client:
    def __init__(self, websocket: Any) -> None:
        self.websocket = websocket
        self.symbol: str | None = None
        self.interval = "1"
        self.force_detail = False
        self.pump_scan_symbol: str | None = None
        self.pump_scan_interval = "15"
        self.force_pump_scan_detail = False
        self.x2_retrace_symbol: str | None = None
        self.x2_retrace_interval = "60"
        self.force_x2_retrace_detail = False
        self.pump_strategy_symbol: str | None = None
        self.pump_strategy_interval = "15"
        self.force_pump_strategy_detail = False


class Hub:
    def __init__(self) -> None:
        self.cache = MarketCache()
        self.paper = PaperCache()
        self.clients: set[Client] = set()
        self.paper_dirty = False
        self.demo = False
        self.board_dirty = False
        self.pump_scan_dirty = False
        self.x2_retrace_dirty = False
        self.pump_strategy_dirty = False
        self.market_dirty = False
        self._stopped = False
        self._stats_cache: dict[str, Any] | None = None
        self._stats_at = 0.0

    def load_demo(self) -> None:
        columns = demo_board()
        self.cache.columns = columns
        self.cache._reindex()
        market = demo_market(columns)
        self.cache.klines = market["klines"]
        from ws_server.cache import _ensure_book_side_maps

        demo_book = dict(market["book"])
        _ensure_book_side_maps(demo_book)
        self.cache.books["BEAMUSDT"] = demo_book
        self.cache.liquidations["BEAMUSDT"] = market["liquidations"]
        self.cache.oi["BEAMUSDT"] = market["oi"]
        self.cache.cvd["BEAMUSDT"] = market["cvd"]
        self.cache.funding["BEAMUSDT"] = market["funding"]
        self.demo = True
        self.board_dirty = True
        self.market_dirty = True
        log.info("Redis недоступен, на странице пример доски")

    def stats(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._stats_cache is not None and now - self._stats_at < 5:
            return self._stats_cache
        calculated = compute_stats(config.SQLITE_PATH)
        if calculated["count"] == 0 and self.demo:
            calculated = demo_stats()
        self._stats_cache = calculated
        self._stats_at = now
        return calculated

    def snapshot(self, client: Client) -> dict[str, Any]:
        board = self.cache.view_board()
        symbol = client.symbol or _first_symbol(board)
        client.symbol = symbol
        pump_symbol = client.pump_scan_symbol
        return {
            "type": "snapshot",
            "demo": self.demo,
            "board": board,
            "pump_scan_board": self.cache.view_pump_scan_board(),
            "stats": self.stats(),
            "detail": self.cache.detail(symbol, client.interval) if symbol else None,
            "pump_scan_detail": (
                self.cache.pump_scan_detail(pump_symbol, client.pump_scan_interval) if pump_symbol else None
            ),
            "x2_retrace_board": self.cache.view_x2_retrace_board(),
            "x2_retrace_detail": (
                self.cache.x2_retrace_detail(client.x2_retrace_symbol, client.x2_retrace_interval)
                if client.x2_retrace_symbol
                else None
            ),
            "pump_strategy_board": self.cache.view_pump_strategy_board(),
            "pump_strategy_detail": (
                self.cache.pump_strategy_detail(
                    client.pump_strategy_symbol, client.pump_strategy_interval
                )
                if client.pump_strategy_symbol
                else None
            ),
            "paper_test": self.paper.view(),
        }

    def on_client(self, client: Client, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "ping":
            return
        if kind == "select":
            symbol = str(message.get("symbol") or "")
            if symbol in self.cache.signals:
                client.symbol = symbol
                client.force_detail = True
        elif kind == "interval":
            interval = str(message.get("interval") or "1")
            if interval in {"1", "5", "15", "60", "240", "D"}:
                client.interval = interval
                client.force_detail = True
        elif kind == "select_pump_scan":
            symbol = str(message.get("symbol") or "")
            if symbol in self.cache.pump_scan_signals:
                client.pump_scan_symbol = symbol
                client.force_pump_scan_detail = True
        elif kind == "pump_scan_interval":
            interval = str(message.get("interval") or "15")
            if interval in {"1", "5", "15", "30", "60", "240", "D"}:
                client.pump_scan_interval = interval
                client.force_pump_scan_detail = True
        elif kind == "select_x2_retrace":
            symbol = str(message.get("symbol") or "")
            if symbol in self.cache.x2_retrace_signals:
                client.x2_retrace_symbol = symbol
                client.force_x2_retrace_detail = True
        elif kind == "x2_retrace_interval":
            interval = str(message.get("interval") or "60")
            if interval in {"1", "5", "15", "30", "60", "240", "D"}:
                client.x2_retrace_interval = interval
                client.force_x2_retrace_detail = True
        elif kind == "select_pump_strategy":
            symbol = str(message.get("symbol") or "")
            if symbol in self.cache.pump_strategy_by_symbol:
                client.pump_strategy_symbol = symbol
                client.force_pump_strategy_detail = True
        elif kind == "pump_strategy_interval":
            interval = str(message.get("interval") or "15")
            if interval in {"1", "5", "15", "30", "60", "240", "D"}:
                client.pump_strategy_interval = interval
                client.force_pump_strategy_detail = True

    async def run(self) -> None:
        flush = asyncio.create_task(self._flush_loop())
        try:
            while not self._stopped:
                try:
                    await self._listen_redis()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning(
                        "Поток Redis недоступен: %s: %s",
                        type(exc).__name__,
                        exc,
                        exc_info=True,
                    )
                    if not self.cache.signals:
                        self.load_demo()
                    await asyncio.sleep(5)
        finally:
            flush.cancel()
            try:
                await flush
            except asyncio.CancelledError:
                pass

    def stop(self) -> None:
        self._stopped = True

    async def _listen_redis(self) -> None:
        import redis.asyncio as redis_async

        client = redis_async.from_url(
            config.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        try:
            await asyncio.wait_for(client.ping(), timeout=2)
        except Exception:
            await client.aclose()
            raise
        pubsub = client.pubsub()
        await pubsub.subscribe(
            config.REDIS_CHANNEL_SIGNALS,
            config.REDIS_CHANNEL_MARKET,
        )
        log.info("Веб-сервер слушает сигналы и рынок")
        try:
            while not self._stopped:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message or message.get("type") != "message":
                    continue
                payload = _decode(message.get("data"))
                if payload is None:
                    continue
                if payload.get("type") == "paper_test":
                    if self.paper.apply(payload):
                        self.paper_dirty = True
                    continue
                kind = self.cache.apply(payload)
                if kind == "board":
                    self.demo = False
                    self.board_dirty = True
                    self._stats_cache = None
                elif kind == "pump_scan":
                    self.demo = False
                    self.pump_scan_dirty = True
                elif kind == "x2_retrace":
                    self.demo = False
                    self.x2_retrace_dirty = True
                elif kind == "pump_strategy":
                    self.demo = False
                    self.pump_strategy_dirty = True
                elif kind == "market":
                    self.market_dirty = True
        finally:
            await pubsub.unsubscribe(
                config.REDIS_CHANNEL_SIGNALS,
                config.REDIS_CHANNEL_MARKET,
            )
            await pubsub.aclose()
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()

    async def _flush_loop(self) -> None:
        tick = 1 / max(config.WS_MAX_HZ, 1)
        ticker_gap = config.TICKER_BATCH_INTERVAL_MS / 1000
        last_ticker = 0.0
        while not self._stopped:
            await asyncio.sleep(tick)
            now = time.monotonic()
            board = self.cache.view_board() if self.board_dirty else None
            pump_board = self.cache.view_pump_scan_board() if self.pump_scan_dirty else None
            x2_board = self.cache.view_x2_retrace_board() if self.x2_retrace_dirty else None
            pump_strategy = (
                self.cache.view_pump_strategy_board() if self.pump_strategy_dirty else None
            )
            send_detail = self.market_dirty
            paper = self.paper.view() if self.paper_dirty else None
            self.board_dirty = False
            self.pump_scan_dirty = False
            self.x2_retrace_dirty = False
            self.pump_strategy_dirty = False
            self.market_dirty = False
            self.paper_dirty = False
            pnl = None
            if now - last_ticker >= ticker_gap:
                pnl = self.cache.pnl_items()
                last_ticker = now
            for client in list(self.clients):
                try:
                    if board is not None:
                        await client.websocket.send_json({"type": "board", "data": board, "demo": self.demo})
                        if not client.symbol:
                            client.symbol = _first_symbol(board)
                            client.force_detail = bool(client.symbol)
                    if pump_board is not None:
                        await client.websocket.send_json(
                            {"type": "pump_scan_board", "data": pump_board, "demo": self.demo}
                        )
                        if not client.pump_scan_symbol:
                            client.pump_scan_symbol = _first_symbol(pump_board)
                            client.force_pump_scan_detail = bool(client.pump_scan_symbol)
                    if x2_board is not None:
                        await client.websocket.send_json(
                            {"type": "x2_retrace_board", "data": x2_board, "demo": self.demo}
                        )
                        if not client.x2_retrace_symbol:
                            client.x2_retrace_symbol = _first_symbol(x2_board)
                            client.force_x2_retrace_detail = bool(client.x2_retrace_symbol)
                    if pump_strategy is not None:
                        await client.websocket.send_json(
                            {
                                "type": "pump_strategy_board",
                                "data": pump_strategy,
                                "demo": self.demo,
                            }
                        )
                    if client.symbol and (send_detail or client.force_detail):
                        await client.websocket.send_json(
                            {
                                "type": "detail",
                                "symbol": client.symbol,
                                "data": self.cache.detail(client.symbol, client.interval),
                            }
                        )
                        client.force_detail = False
                    if client.pump_scan_symbol and (send_detail or client.force_pump_scan_detail):
                        await client.websocket.send_json(
                            {
                                "type": "pump_scan_detail",
                                "symbol": client.pump_scan_symbol,
                                "data": self.cache.pump_scan_detail(
                                    client.pump_scan_symbol, client.pump_scan_interval
                                ),
                            }
                        )
                        client.force_pump_scan_detail = False
                    if client.x2_retrace_symbol and (send_detail or client.force_x2_retrace_detail):
                        await client.websocket.send_json(
                            {
                                "type": "x2_retrace_detail",
                                "symbol": client.x2_retrace_symbol,
                                "data": self.cache.x2_retrace_detail(
                                    client.x2_retrace_symbol, client.x2_retrace_interval
                                ),
                            }
                        )
                        client.force_x2_retrace_detail = False
                    if client.pump_strategy_symbol and (send_detail or client.force_pump_strategy_detail):
                        await client.websocket.send_json(
                            {
                                "type": "pump_strategy_detail",
                                "symbol": client.pump_strategy_symbol,
                                "data": self.cache.pump_strategy_detail(
                                    client.pump_strategy_symbol,
                                    client.pump_strategy_interval,
                                ),
                            }
                        )
                        client.force_pump_strategy_detail = False
                    if pnl is not None:
                        await client.websocket.send_json({"type": "pnl", "items": pnl})
                    if paper is not None:
                        await client.websocket.send_json({"type": "paper_test", "data": paper})
                except Exception:
                    self.clients.discard(client)


def _first_symbol(columns: list[dict[str, Any]]) -> str | None:
    for column in columns:
        for signal in column.get("signals") or []:
            if signal.get("symbol"):
                return str(signal["symbol"])
    return None


def _decode(raw: object) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
