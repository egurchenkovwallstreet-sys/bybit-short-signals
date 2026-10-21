"""Сводка статистики: шорт/лонг и календарные периоды."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from signal_engine.paper.stats_dashboard import compute_paper_stats_dashboard, last_msk_days

MSK = timezone(timedelta(hours=3))


def _write_db(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
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
            id, symbol, variant, status, side, kind, opened_at, closed_at,
            entry_price, exit_price, pnl_usd, roe_pct, entry_fee, exit_fee, funding_paid, entry_json, exit_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


class PaperStatsDashboardTest(unittest.TestCase):
    def test_side_split_and_variant_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "paper.db"
            _write_db(
                path,
                [
                    (1, "AAAUSDT", "em6", "closed", "short", "", 0, 1000, 1, 1, 10, 5, 0.1, 0.1, 0, "{}", "trailing_stop"),
                    (2, "BBBUSDT", "em6", "closed", "long", "", 0, 2000, 1, 1, -4, -2, 0.1, 0.1, 0, "{}", "trailing_stop"),
                ],
            )
            stats = compute_paper_stats_dashboard(path)
        em6 = next(v for v in stats["variants"] if v["id"] == "em6")
        self.assertEqual(em6["metrics"]["closed"], 2)
        self.assertEqual(em6["sides"]["short"]["n"], 1)
        self.assertEqual(em6["sides"]["short"]["net"], 10.0)
        self.assertEqual(em6["sides"]["long"]["n"], 1)
        self.assertEqual(em6["sides"]["long"]["net"], -4.0)

    def test_last_msk_days_count(self) -> None:
        ms = int(datetime(2024, 1, 15, 12, 0, tzinfo=MSK).timestamp() * 1000)
        days = last_msk_days(ms, 10)
        self.assertEqual(len(days), 10)
        self.assertEqual(days[-1]["label"], "15.01")


if __name__ == "__main__":
    unittest.main()
