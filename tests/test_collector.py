"""Проверки коллектора без сети и без Redis."""

from __future__ import annotations

import asyncio
import json
import unittest

from collector.buffer import DropOldestQueue
from collector.normalize import (
    kline_message,
    messages_from_frame,
    oi_message,
    orderbook_from_rest,
)
from collector.publisher import RedisPublisher
from collector.rest_client import is_tracked_contract, symbols_from_instruments
from collector.topics import reconnect_delay, shard_symbols, subscribe_requests, topics_for_symbol
from collector.ws_client import BybitWsClient


TRADE_FRAME = {
    "topic": "publicTrade.BEAMUSDT",
    "type": "snapshot",
    "ts": 1700000000000,
    "data": [
        {
            "T": 1700000000001,
            "s": "BEAMUSDT",
            "S": "Buy",
            "v": "10",
            "p": "0.025",
            "i": "trade-1",
            "BT": False,
        }
    ],
}

LIQ_FRAME = {
    "topic": "allLiquidation.BEAMUSDT",
    "type": "snapshot",
    "ts": 1700000000100,
    "data": [
        {"T": 1700000000090, "s": "BEAMUSDT", "S": "Sell", "v": "200", "p": "0.03"}
    ],
}


class NormalizeTest(unittest.TestCase):
    def test_trade(self) -> None:
        events = messages_from_frame(TRADE_FRAME)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["symbol"], "BEAMUSDT")
        self.assertEqual(event["type"], "trade")
        self.assertEqual(event["timestamp"], 1700000000001)
        self.assertEqual(event["data"]["price"], 0.025)
        self.assertEqual(event["data"]["side"], "Buy")
        self.assertEqual(event["data"]["trade_id"], "trade-1")

    def test_short_liquidation_passes_side(self) -> None:
        events = messages_from_frame(LIQ_FRAME)
        self.assertEqual(events[0]["type"], "liquidation")
        self.assertEqual(events[0]["data"]["side"], "Sell")
        self.assertEqual(events[0]["data"]["size"], 200.0)

    def test_orderbook_delta_keeps_zero_size(self) -> None:
        frame = {
            "topic": "orderbook.50.BEAMUSDT",
            "type": "delta",
            "ts": 1700000000200,
            "data": {
                "s": "BEAMUSDT",
                "b": [["0.02", "0"]],
                "a": [["0.03", "5"]],
                "u": 15,
                "seq": 100,
            },
        }
        event = messages_from_frame(frame)[0]
        self.assertEqual(event["type"], "orderbook")
        self.assertEqual(event["data"]["kind"], "delta")
        self.assertFalse(event["data"]["reset"])
        self.assertEqual(event["data"]["bids"], [[0.02, 0.0]])
        self.assertEqual(event["data"]["source"], "ws")

    def test_orderbook_reset_flag(self) -> None:
        frame = {
            "topic": "orderbook.50.BEAMUSDT",
            "type": "delta",
            "ts": 1,
            "data": {"s": "BEAMUSDT", "b": [], "a": [], "u": 1},
        }
        event = messages_from_frame(frame)[0]
        self.assertTrue(event["data"]["reset"])

    def test_ticker_delta_is_partial(self) -> None:
        frame = {
            "topic": "tickers.BEAMUSDT",
            "type": "delta",
            "ts": 1700000000300,
            "data": {"symbol": "BEAMUSDT", "fundingRate": "0.0008"},
        }
        event = messages_from_frame(frame)[0]
        self.assertEqual(event["type"], "ticker")
        self.assertTrue(event["data"]["partial"])
        self.assertEqual(event["data"]["funding_rate"], 0.0008)
        self.assertNotIn("last_price", event["data"])

    def test_control_frames_are_ignored(self) -> None:
        self.assertEqual(messages_from_frame({"op": "ping", "success": True}), [])
        self.assertEqual(messages_from_frame({"op": "subscribe", "success": True}), [])

    def test_deprecated_liquidation_topic_is_not_parsed(self) -> None:
        frame = {
            "topic": "liquidation.BEAMUSDT",
            "data": [{"T": 1, "s": "BEAMUSDT", "S": "Sell", "v": "1", "p": "1"}],
        }
        self.assertEqual(messages_from_frame(frame), [])

    def test_kline_sorted_ascending(self) -> None:
        message = kline_message(
            "BEAMUSDT",
            "60",
            [
                ["2000", "2", "3", "1", "2.5", "10", "25"],
                ["1000", "1", "2", "0.5", "1.5", "8", "12"],
            ],
        )
        assert message is not None
        self.assertEqual(message["type"], "kline")
        self.assertEqual([c["timestamp"] for c in message["data"]["candles"]], [1000, 2000])
        self.assertEqual(message["data"]["candles"][1]["turnover"], 25.0)

    def test_open_interest(self) -> None:
        message = oi_message(
            "BEAMUSDT",
            "5min",
            [
                {"openInterest": "30", "timestamp": "2000"},
                {"openInterest": "10", "timestamp": "1000"},
            ],
        )
        assert message is not None
        self.assertEqual(message["type"], "open_interest")
        self.assertEqual(message["data"]["points"][0]["open_interest"], 10.0)

    def test_rest_orderbook_snapshot(self) -> None:
        event = orderbook_from_rest(
            {"s": "BEAMUSDT", "b": [["1", "2"]], "a": [["3", "4"]], "ts": 50, "u": 7}
        )
        assert event is not None
        self.assertEqual(event["data"]["source"], "rest")
        self.assertTrue(event["data"]["reset"])
        self.assertEqual(event["symbol"], "BEAMUSDT")


class TopicsTest(unittest.TestCase):
    def test_topics_use_all_liquidation(self) -> None:
        topics = topics_for_symbol("BEAMUSDT")
        self.assertEqual(
            topics,
            [
                "publicTrade.BEAMUSDT",
                "allLiquidation.BEAMUSDT",
                "orderbook.50.BEAMUSDT",
                "tickers.BEAMUSDT",
            ],
        )
        self.assertNotIn("liquidation.BEAMUSDT", topics)

    def test_reconnect_backoff(self) -> None:
        self.assertEqual([reconnect_delay(i) for i in range(6)], [1, 2, 4, 8, 8, 8])

    def test_shard_by_symbol_cap(self) -> None:
        symbols = [f"S{i}USDT" for i in range(5)]
        groups = shard_symbols(symbols, per_connection=2, max_args_chars=21000)
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups[0], ["S0USDT", "S1USDT"])
        self.assertEqual(groups[-1], ["S4USDT"])

    def test_shard_by_char_budget(self) -> None:
        symbols = ["BTCUSDT", "ETHUSDT"]
        groups = shard_symbols(symbols, per_connection=50, max_args_chars=80)
        self.assertEqual(len(groups), 2)

    def test_subscribe_batches(self) -> None:
        requests = subscribe_requests(["BTCUSDT", "ETHUSDT"], batch_size=10)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["op"], "subscribe")
        self.assertEqual(len(requests[0]["args"]), 8)
        smaller = subscribe_requests(["BTCUSDT"], batch_size=3)
        self.assertEqual(len(smaller), 2)
        self.assertEqual(len(smaller[0]["args"]), 3)


class InstrumentsTest(unittest.TestCase):
    def test_filters_dated_and_inverse(self) -> None:
        payload = {
            "retCode": 0,
            "result": {
                "list": [
                    {"symbol": "BTCUSDT", "quoteCoin": "USDT", "contractType": "LinearPerpetual", "status": "Trading"},
                    {"symbol": "BTCUSDT-26DEC25", "quoteCoin": "USDT", "contractType": "LinearFutures", "status": "Trading"},
                    {"symbol": "ETHUSDT", "quoteCoin": "USDT", "contractType": "LinearPerpetual", "status": "Closed"},
                    {"symbol": "BTCUSD", "quoteCoin": "USD", "contractType": "LinearPerpetual", "status": "Trading"},
                ],
                "nextPageCursor": "next",
            },
        }
        symbols, cursor = symbols_from_instruments(payload)
        self.assertEqual(symbols, ["BTCUSDT"])
        self.assertEqual(cursor, "next")
        self.assertFalse(is_tracked_contract(payload["result"]["list"][1]))


class BufferTest(unittest.TestCase):
    def test_drops_oldest(self) -> None:
        queue = DropOldestQueue(2)
        queue.put("a")
        queue.put("b")
        queue.put("c")
        self.assertEqual(queue.dropped, 1)

        async def take() -> list[str]:
            return [await queue.get(), await queue.get()]

        self.assertEqual(asyncio.run(take()), ["b", "c"])


class _FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


class PublisherTest(unittest.TestCase):
    def test_publishes_newest_when_buffer_overflows(self) -> None:
        async def scenario() -> list[dict]:
            redis = _FakeRedis()
            publisher = RedisPublisher(redis, "market:data", maxsize=2)
            publisher.publish({"symbol": "A", "timestamp": 1, "type": "trade", "data": {}})
            publisher.publish({"symbol": "B", "timestamp": 2, "type": "trade", "data": {}})
            publisher.publish({"symbol": "C", "timestamp": 3, "type": "trade", "data": {}})
            await publisher.start()
            for _ in range(20):
                if len(redis.published) >= 2:
                    break
                await asyncio.sleep(0.01)
            await publisher.stop()
            return [json.loads(payload) for _, payload in redis.published]

        messages = asyncio.run(scenario())
        self.assertEqual([item["symbol"] for item in messages], ["B", "C"])


class _FakeSocket:
    def __init__(self, frames: list[str]) -> None:
        self.frames = frames
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for frame in self.frames:
            yield frame
        await asyncio.sleep(3600)


class _FakeConnect:
    def __init__(self, socket: _FakeSocket) -> None:
        self.socket = socket

    async def __aenter__(self) -> _FakeSocket:
        return self.socket

    async def __aexit__(self, *args: object) -> bool:
        return False


class WsClientTest(unittest.TestCase):
    def test_subscribe_and_emit_trade(self) -> None:
        async def scenario() -> tuple[list[dict], list[str]]:
            socket = _FakeSocket([json.dumps(TRADE_FRAME)])
            received: list[dict] = []
            snapshots: list[list[str]] = []

            async def on_messages(messages: list[dict]) -> None:
                received.extend(messages)

            async def on_connected(symbols: list[str]) -> None:
                snapshots.append(list(symbols))

            client = BybitWsClient(
                "wss://example",
                ["BEAMUSDT"],
                on_messages,
                on_connected,
                connect=lambda: _FakeConnect(socket),
                ping_interval=0,
            )
            task = asyncio.create_task(client.run())
            for _ in range(50):
                if received:
                    break
                await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return received, [item["op"] for item in socket.sent]

        received, ops = asyncio.run(scenario())
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["type"], "trade")
        self.assertIn("subscribe", ops)


if __name__ == "__main__":
    unittest.main()
