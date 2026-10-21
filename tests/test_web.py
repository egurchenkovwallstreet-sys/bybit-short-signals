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
    def test_paper_dashboard_global_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "paper.db"
            conn = __import__("sqlite3").connect(path)
            conn.executescript(
                """
                CREATE TABLE paper_trades (
                    id INTEGER PRIMARY KEY, symbol TEXT, variant TEXT, status TEXT, side TEXT, kind TEXT,
                    opened_at INTEGER, closed_at INTEGER, entry_price REAL, exit_price REAL,
                    pnl_usd REAL, roe_pct REAL, entry_fee REAL, exit_fee REAL, funding_paid REAL,
                    entry_json TEXT, exit_reason TEXT
                );
                CREATE TABLE paper_equity_v (variant TEXT, ts INTEGER, balance REAL, equity REAL);
                """
            )
            conn.executemany(
                """
                INSERT INTO paper_trades (
                    id, symbol, variant, status, side, opened_at, closed_at, pnl_usd, roe_pct,
                    entry_fee, exit_fee, funding_paid, entry_json, exit_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, '{}', 'trailing_stop')
                """,
                [
                    (1, "AAAUSDT", "t20", "closed", "short", 0, 1000, 40.0, 4.0),
                    (2, "BBBUSDT", "t20", "closed", "short", 0, 2000, -100.0, -10.0),
                ],
            )
            conn.commit()
            conn.close()
            stats = compute_stats(path)
        self.assertTrue(stats.get("paper"))
        metrics = stats["global"]["metrics"]
        self.assertEqual(metrics["closed"], 2)
        self.assertEqual(metrics["win_rate"], 50.0)
        self.assertEqual(metrics["profit_factor"], 0.4)


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
