"""Журнал тестовых сигналов BTC."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS btc_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
    mode TEXT NOT NULL,
    side TEXT NOT NULL,
    grade TEXT NOT NULL,
    score INTEGER NOT NULL,
    entry_ts INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    exit_ts INTEGER,
    exit_price REAL,
    outcome TEXT,
    pnl_pct REAL,
    r_multiple REAL,
    exit_reason TEXT,
    checks_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_btc_signals_open ON btc_signals(mode, exit_ts);
"""


class BtcStrategyStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate_symbol_column()
        self._conn.commit()

    def _migrate_symbol_column(self) -> None:
        assert self._conn is not None
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(btc_signals)")}
        if "symbol" not in cols:
            self._conn.execute(
                "ALTER TABLE btc_signals ADD COLUMN symbol TEXT NOT NULL DEFAULT 'BTCUSDT'"
            )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def insert_signal(
        self,
        symbol: str,
        mode: str,
        side: str,
        grade: str,
        score: int,
        entry_ts: int,
        entry_price: float,
        checks: dict[str, bool],
        created_at: int,
    ) -> int:
        assert self._conn is not None
        cur = self._conn.execute(
            """
            INSERT INTO btc_signals
            (symbol, mode, side, grade, score, entry_ts, entry_price, checks_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                mode,
                side,
                grade,
                score,
                entry_ts,
                entry_price,
                json.dumps(checks, ensure_ascii=False),
                created_at,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def close_signal(
        self,
        signal_id: int,
        exit_ts: int,
        exit_price: float,
        outcome: str,
        pnl_pct: float,
        r_multiple: float,
        exit_reason: str,
    ) -> None:
        assert self._conn is not None
        self._conn.execute(
            """
            UPDATE btc_signals SET exit_ts=?, exit_price=?, outcome=?, pnl_pct=?, r_multiple=?, exit_reason=?
            WHERE id=?
            """,
            (exit_ts, exit_price, outcome, pnl_pct, r_multiple, exit_reason, signal_id),
        )
        self._conn.commit()

    def open_positions(self, symbol: str) -> list[dict[str, Any]]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM btc_signals WHERE exit_ts IS NULL AND symbol = ? ORDER BY id",
            (symbol,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_signals(self, limit: int = 200, symbol: str | None = None) -> list[dict[str, Any]]:
        assert self._conn is not None
        if symbol:
            rows = self._conn.execute(
                "SELECT * FROM btc_signals WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM btc_signals ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["checks"] = json.loads(item.pop("checks_json") or "{}")
            out.append(item)
        return out
