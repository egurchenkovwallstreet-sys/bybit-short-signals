"""Статистика, стакан и ссылка на Bybit. Страницу отдельно проверяет браузер."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from signal_engine.models import Signal
from signal_engine.store import SignalStore
from ws_server.app import bybit_trade_url
from ws_server.cache import MarketCache, merge_kline_candles
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

    def test_orderbook_after_demo_list_book(self) -> None:
        cache = MarketCache()
        cache.books["BEAMUSDT"] = {
            "bids": [[100.0, 50.0]],
            "asks": [[101.0, 40.0]],
            "walls": [],
        }
        cache.apply(
            {
                "symbol": "BEAMUSDT",
                "timestamp": 1,
                "type": "orderbook",
                "data": {"kind": "delta", "bids": [[100.0, 60.0]], "asks": []},
            }
        )
        view = cache.book_view("BEAMUSDT")
        self.assertEqual(view["bids"][0][1], 60.0)

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


class KlineTailMergeTest(unittest.TestCase):
    def test_tail_overwrites_same_bar_and_appends(self) -> None:
        merged = merge_kline_candles(
            [{"timestamp": 1, "close": 1}, {"timestamp": 2, "close": 2}],
            [{"timestamp": 2, "close": 2.5}, {"timestamp": 3, "close": 3}],
        )
        self.assertEqual([row["close"] for row in merged], [1, 2.5, 3])

    def test_vacuum_scan_pivots_kept(self) -> None:
        cache = MarketCache()
        cache.apply(
            {
                "type": "vacuum_lh_board",
                "timestamp": 10,
                "data": {
                    "intervals": {"15": [{"symbol": "ABCUSDT", "all_peaks": [{"time_ms": 1, "price": 2}]}]},
                    "default_interval": "15",
                    "chart_pivots": {"5": {"ABCUSDT": {"all_peaks": [{"time_ms": 5, "price": 3}]}}},
                },
            }
        )
        self.assertEqual(cache.vacuum_lh_chart_pivots["5"]["ABCUSDT"]["all_peaks"][0]["price"], 3)
        self.assertIn("5", cache.view_vacuum_lh_board("15")["chart_pivots"])


class BybitLinkTest(unittest.TestCase):
    def test_only_ticker_characters(self) -> None:
        self.assertIn("BEAMUSDT", bybit_trade_url("BEAMUSDT"))
        with self.assertRaises(HTTPException):
            bybit_trade_url("../etc")


if __name__ == "__main__":
    unittest.main()
