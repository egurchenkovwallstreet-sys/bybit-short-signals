"""Закрытые сделки: фильтр по монете для графика пылесоса."""

from __future__ import annotations

import sqlite3
import unittest

from signal_engine.paper.analytics import list_trades


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY,
            symbol TEXT,
            variant TEXT,
            status TEXT,
            side TEXT,
            opened_at INTEGER,
            closed_at INTEGER,
            entry_price REAL,
            worst_price REAL,
            best_price REAL,
            exit_price REAL,
            last_price REAL,
            pnl_usd REAL,
            roe_pct REAL,
            entry_json TEXT,
            exit_json TEXT
        )
        """
    )
    rows = [
        (1, "AAAUSDT", "pyl", "closed", "short", 10, 20, 1.0, 1.2, 0.8, 0.9, 0.9, 3.0, 4.0),
        (2, "BBBUSDT", "pyl", "closed", "long", 11, 21, 2.0, 1.5, 2.4, 2.2, 2.2, 1.0, 2.0),
        (3, "AAAUSDT", "vps5", "closed", "long", 12, 22, 1.0, 0.7, 1.4, 1.3, 1.3, 2.0, 5.0),
        (4, "AAAUSDT", "pyl", "open", "short", 13, None, 1.0, 1.1, 0.9, None, 1.0, None, None),
    ]
    conn.executemany(
        """
        INSERT INTO paper_trades (
            id, symbol, variant, status, side, opened_at, closed_at,
            entry_price, worst_price, best_price, exit_price, last_price, pnl_usd, roe_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return conn


class ListTradesSymbolTest(unittest.TestCase):
    def test_symbol_keeps_worst_price_for_that_coin(self) -> None:
        conn = _conn()
        rows = list_trades(conn, "closed", 50, "pyl", "AAAUSDT")
        self.assertEqual([row["id"] for row in rows], [1])
        self.assertEqual(rows[0]["worst_price"], 1.2)
        self.assertEqual(rows[0]["side"], "short")
        self.assertEqual(rows[0]["exit_price"], 0.9)

    def test_without_symbol_returns_variant(self) -> None:
        conn = _conn()
        rows = list_trades(conn, "closed", 50, "pyl")
        self.assertEqual({row["symbol"] for row in rows}, {"AAAUSDT", "BBBUSDT"})


if __name__ == "__main__":
    unittest.main()
