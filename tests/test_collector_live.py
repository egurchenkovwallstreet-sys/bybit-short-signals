"""Живая проверка Bybit: список пар, REST и короткий поток BTCUSDT.

Сеть нужна, поэтому тест молчит, пока не задано COLLECTOR_LIVE=1:

    set COLLECTOR_LIVE=1
    python -m unittest tests.test_collector_live
"""

from __future__ import annotations

import asyncio
import os
import unittest

import config
from collector.rest_client import BybitRest
from collector.ws_client import BybitWsClient


LIVE = os.environ.get("COLLECTOR_LIVE") == "1"


@unittest.skipUnless(LIVE, "Живой тест Bybit выключен. Задайте COLLECTOR_LIVE=1.")
class LiveBybitTest(unittest.TestCase):
    def test_market_stream(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        rest = BybitRest()
        await rest.open()
        try:
            symbols = await rest.list_usdt_perpetuals()
            self.assertGreater(len(symbols), 400)
            self.assertIn("BTCUSDT", symbols)

            candles = await rest.fetch_klines("BTCUSDT", "1")
            assert candles is not None
            self.assertEqual(candles["type"], "kline")
            self.assertGreater(len(candles["data"]["candles"]), 10)

            oi = await rest.fetch_open_interest("BTCUSDT", "5min")
            assert oi is not None
            self.assertEqual(oi["type"], "open_interest")
            self.assertGreater(len(oi["data"]["points"]), 0)

            book = await rest.fetch_orderbook_snapshot("BTCUSDT")
            assert book is not None
            self.assertEqual(book["data"]["source"], "rest")
            self.assertGreater(len(book["data"]["bids"]), 0)
            self.assertGreater(len(book["data"]["asks"]), 0)
        finally:
            await rest.close()

        received: list[dict] = []
        ready = asyncio.Event()

        async def on_messages(messages: list[dict]) -> None:
            received.extend(messages)
            kinds = {item["type"] for item in received}
            if {"trade", "orderbook", "ticker"} <= kinds:
                ready.set()

        client = BybitWsClient(
            config.BYBIT_WS_PUBLIC_LINEAR,
            ["BTCUSDT"],
            on_messages,
            name="live",
        )
        task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(ready.wait(), timeout=30)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        kinds = {item["type"] for item in received}
        self.assertIn("trade", kinds)
        self.assertIn("orderbook", kinds)
        self.assertIn("ticker", kinds)
        self.assertTrue(all(item["symbol"] == "BTCUSDT" for item in received))
        trade = next(item for item in received if item["type"] == "trade")
        self.assertGreater(trade["data"]["price"], 0)
        book_event = next(item for item in received if item["type"] == "orderbook")
        self.assertIn(book_event["data"]["kind"], {"snapshot", "delta"})
