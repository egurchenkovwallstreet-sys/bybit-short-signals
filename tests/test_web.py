"""Статистика, стакан и ссылка на Bybit. Страницу отдельно проверяет браузер."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from signal_engine.models import Signal
from signal_engine.store import SignalStore
from ws_server.app import bybit_trade_url
from ws_server.cache import MarketCache
from ws_server.stats import compute_stats
from fastapi import HTTPException


def _signal(symbol: str, pnl: float, created_at: int) -> Signal:
    signal = Signal(
        symbol=symbol,
        created_at=created_at,
        updated_at=created_at,
        entry_price=100,
        last_price=100,
        strength=5,
        rating=80,
        probability=60,
        quality=2,
        tf_match=1,
        extra=1,
        color="green",
        status="ВХОД",
        label="5/5",
        outcome="TP_HIT" if pnl > 0 else "LIQUIDATED",
        pnl_pct=pnl,
        exit_at=created_at + 1000,
    )
    return signal


class StatsTest(unittest.TestCase):
    def test_win_rate_factor_and_drawdown(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "signals.db"
            store = SignalStore(path)
            store.open()
            first = _signal("AAAUSDT", 40, 1_000)
            second = _signal("BBBUSDT", -100, 2_000)
            store.insert(first)
            store.insert(second)
            store.update(first)
            store.update(second)
            store.close()
            stats = compute_stats(path)
        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["win_rate"], 50.0)
        self.assertEqual(stats["profit_factor"], 0.4)
        self.assertEqual(stats["avg_return"], -30.0)
        # 100 → 140 → 40. Просадка от 140 до 40 = 100 / 140.
        self.assertAlmostEqual(stats["max_drawdown"], 100 / 140 * 100, places=2)


class BookTest(unittest.TestCase):
    def test_delta_removes_empty_level(self) -> None:
        cache = MarketCache()
        cache.apply(
            {
                "symbol": "BTCUSDT",
                "timestamp": 1,
                "type": "orderbook",
                "data": {
                    "kind": "snapshot",
                    "reset": True,
                    "bids": [[100, 2], [99, 8]],
                    "asks": [[101, 1]],
                },
            }
        )
        cache.apply(
            {
                "symbol": "BTCUSDT",
                "timestamp": 2,
                "type": "orderbook",
                "data": {"kind": "delta", "bids": [[100, 0]], "asks": []},
            }
        )
        view = cache.book_view("BTCUSDT")
        prices = [row[0] for row in view["bids"]]
        self.assertNotIn(100, prices)
        self.assertIn(99, prices)

    def test_bad_timestamp_does_not_crash_market(self) -> None:
        cache = MarketCache()
        cache.apply(
            {
                "symbol": "BTCUSDT",
                "timestamp": {},
                "type": "trade",
                "data": {"price": 100, "size": 1, "side": "Buy"},
            }
        )
        self.assertIn("BTCUSDT", cache.mini)

    def test_trade_updates_short_pnl(self) -> None:
        cache = MarketCache()
        cache.apply(
            {
                "type": "board",
                "data": {
                    "columns": [
                        {
                            "strength": 5,
                            "color": "green",
                            "status": "ВХОД",
                            "label": "5/5",
                            "signals": [
                                {
                                    "symbol": "BEAMUSDT",
                                    "strength": 5,
                                    "entry_price": 100,
                                    "last_price": 100,
                                    "checks": {"pump": True},
                                }
                            ],
                        }
                    ]
                },
            }
        )
        cache.apply(
            {
                "symbol": "BEAMUSDT",
                "timestamp": 5,
                "type": "trade",
                "data": {"price": 97, "size": 1, "side": "Sell"},
            }
        )
        pnl = cache.pnl_items()[0]["pnl_pct"]
        self.assertAlmostEqual(pnl, 30.0)


class BybitLinkTest(unittest.TestCase):
    def test_only_ticker_characters(self) -> None:
        self.assertIn("BEAMUSDT", bybit_trade_url("BEAMUSDT"))
        with self.assertRaises(HTTPException):
            bybit_trade_url("../etc")


if __name__ == "__main__":
    unittest.main()
