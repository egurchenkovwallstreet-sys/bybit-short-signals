"""Процесс тестовой BTC-стратегии: свечи REST, тики из Redis, журнал SQLite."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import config
from collector.publisher import RedisPublisher, open_redis
from collector.rest_client import BybitRest
from strategy_test.analytics import compute_analytics
from strategy_test.engine import BtcStrategyEngine, OpenTrade
from strategy_test.markers import markers_from_signals
from strategy_test.store import BtcStrategyStore


log = logging.getLogger(__name__)

_INTERVALS = ("1", "5", "15", "30", "60", "240", "D")


class BtcStrategyService:
    def __init__(self) -> None:
        self.engine = BtcStrategyEngine()
        self.store = BtcStrategyStore(config.BTC_TEST_SQLITE_PATH)
        self.rest = BybitRest()
        self._pub: RedisPublisher | None = None
        self._pub_redis = None

    async def run(self) -> None:
        self.store.open()
        await self.rest.open()
        self._pub_redis = await open_redis(config.REDIS_URL)
        self._pub = RedisPublisher(
            self._pub_redis,
            config.REDIS_CHANNEL_BTC_TEST,
            config.REDIS_CHANNEL_BUFFER,
        )
        await self._pub.start()
        self._restore_open()
        self._restore_markers()
        await self._publish()
        await asyncio.gather(
            self._kline_loop(),
            self._market_loop(),
            self._scan_loop(),
        )

    def _restore_open(self) -> None:
        for row in self.store.open_positions():
            mode = str(row["mode"])
            risk = abs(float(row["entry_price"]) * 0.005) or 1.0
            self.engine.open[mode] = OpenTrade(
                id=int(row["id"]),
                mode=mode,
                side=str(row["side"]),
                entry_price=float(row["entry_price"]),
                entry_ts=int(row["entry_ts"]),
                stop=float(row["entry_price"]) - risk,
                tp=float(row["entry_price"]) + risk,
                risk=risk,
                max_hold_sec=8 * 3600,
            )

    def _restore_markers(self) -> None:
        rows = self.store.list_signals(120)
        self.engine.markers = markers_from_signals(rows)

    async def _kline_loop(self) -> None:
        while True:
            try:
                for interval in _INTERVALS:
                    msg = await self.rest.fetch_klines(self.engine.SYMBOL, interval)
                    await asyncio.sleep(0.35)
                    if not msg:
                        continue
                    candles = (msg.get("data") or {}).get("candles") or []
                    parsed: list[dict[str, float]] = []
                    for row in candles:
                        parsed.append(
                            {
                                "t": float(row["timestamp"]),
                                "o": float(row["open"]),
                                "h": float(row["high"]),
                                "l": float(row["low"]),
                                "c": float(row["close"]),
                                "v": float(row["volume"]),
                            }
                        )
                    self.engine.set_bars(interval, parsed)
                oi_msg = await self.rest.fetch_open_interest(self.engine.SYMBOL, "15min")
                if oi_msg:
                    points = (oi_msg.get("data") or {}).get("points") or []
                    if points:
                        last = points[-1]
                        self.engine.on_oi(float(last.get("open_interest", 0)), int(last.get("timestamp", 0)))
            except Exception:
                log.exception("Ошибка загрузки свечей BTC")
            await asyncio.sleep(config.BTC_TEST_KLINE_REFRESH_SEC)

    async def _market_loop(self) -> None:
        client = await open_redis(config.REDIS_URL)
        pubsub = client.pubsub()
        await pubsub.subscribe(config.REDIS_CHANNEL_MARKET)
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message or message.get("type") != "message":
                    continue
                raw = message.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                if not isinstance(raw, str):
                    continue
                try:
                    envelope = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if envelope.get("symbol") != config.BTC_TEST_SYMBOL:
                    continue
                self._ingest(envelope)
        finally:
            await pubsub.unsubscribe(config.REDIS_CHANNEL_MARKET)
            await client.aclose()

    def _ingest(self, envelope: dict[str, Any]) -> None:
        kind = envelope.get("type")
        data = envelope.get("data") or {}
        ts = int(envelope.get("timestamp") or time.time() * 1000)
        if kind == "trade":
            price = data.get("price") or data.get("p")
            if price is not None:
                self.engine.on_trade(float(price), ts)
        elif kind == "ticker":
            fr = data.get("fundingRate") or data.get("funding_rate")
            if fr is not None:
                self.engine.on_ticker(float(fr))
        elif kind == "liquidation":
            side = str(data.get("side") or data.get("S") or "")
            usd = float(data.get("value") or data.get("qty") or 0) * float(
                data.get("price") or data.get("p") or self.engine.last_price or 0
            )
            if usd > 0:
                self.engine.on_liquidation(side, usd, ts)
        elif kind == "open_interest":
            val = data.get("openInterest") or data.get("oi")
            if val is not None:
                self.engine.on_oi(float(val), ts)

    async def _scan_loop(self) -> None:
        while True:
            now_ms = int(time.time() * 1000)
            for closed in self.engine.update_exits(now_ms):
                self.store.close_signal(
                    closed["id"],
                    closed["exit_ts"],
                    closed["exit_price"],
                    closed["outcome"],
                    closed["pnl_pct"],
                    closed["r_multiple"],
                    closed["exit_reason"],
                )
            for sig in self.engine.scan_entries(now_ms):
                sid = self.store.insert_signal(
                    sig["mode"],
                    sig["side"],
                    sig["grade"],
                    sig["score"],
                    sig["entry_ts"],
                    sig["entry_price"],
                    sig["checks"],
                    now_ms,
                )
                self.engine.register_open(
                    OpenTrade(
                        id=sid,
                        mode=sig["mode"],
                        side=sig["side"],
                        entry_price=sig["entry_price"],
                        entry_ts=sig["entry_ts"],
                        stop=sig["stop"],
                        tp=sig["tp"],
                        risk=sig["risk"],
                        max_hold_sec=sig["max_hold_sec"],
                    )
                )
                self.engine.markers.append(
                    {
                        "time": sig["entry_ts"] // 1000,
                        "side": sig["side"],
                        "grade": sig["grade"],
                        "mode": sig["mode"],
                        "price": sig["entry_price"],
                    }
                )
            await self._publish()
            await asyncio.sleep(config.BTC_TEST_SCAN_SEC)

    async def _publish(self) -> None:
        if self._pub is None:
            return
        rows = self.store.list_signals(150)
        analytics = compute_analytics(rows)
        payload = {
            "type": "btc_strategy",
            "timestamp": int(time.time() * 1000),
            "data": self.engine.public_state(rows, analytics),
        }
        self._pub.publish(payload)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(BtcStrategyService().run())
    except KeyboardInterrupt:
        log.info("BTC strategy test остановлен")
