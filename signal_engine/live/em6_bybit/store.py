"""Журнал live em6 Bybit Demo."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS em6_bybit_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    status TEXT NOT NULL,
    opened_at INTEGER NOT NULL,
    closed_at INTEGER,
    entry_price REAL NOT NULL,
    exit_price REAL,
    qty REAL NOT NULL,
    margin REAL,
    leverage INTEGER NOT NULL,
    stop_price REAL NOT NULL,
    best_price REAL NOT NULL,
    worst_price REAL NOT NULL,
    max_roe REAL,
    min_roe REAL,
    exit_reason TEXT,
    pnl_usd REAL,
    roe_pct REAL,
    entry_order_id TEXT,
    last_exchange_stop REAL,
    exit_json TEXT
);
CREATE INDEX IF NOT EXISTS em6_bybit_trades_status ON em6_bybit_trades(status);
CREATE INDEX IF NOT EXISTS em6_bybit_trades_symbol ON em6_bybit_trades(symbol);
"""


class Em6BybitStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.PAPER_SQLITE_PATH

    def open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(em6_bybit_trades)")}
        if "profit_lock_armed" not in cols:
            conn.execute(
                "ALTER TABLE em6_bybit_trades ADD COLUMN profit_lock_armed INTEGER NOT NULL DEFAULT 0"
            )
            conn.commit()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(em6_bybit_trades)")}
        if "locked_stop_roe" not in cols:
            conn.execute(
                "ALTER TABLE em6_bybit_trades ADD COLUMN locked_stop_roe REAL NOT NULL DEFAULT -1000"
            )
            conn.commit()
        return conn

    def insert_open(self, conn: sqlite3.Connection, row: dict[str, Any]) -> int:
        cur = conn.execute(
            """
            INSERT INTO em6_bybit_trades(
                symbol, side, status, opened_at, entry_price, qty, margin, leverage,
                stop_price, best_price, worst_price, max_roe, min_roe, entry_order_id,
                last_exchange_stop
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["symbol"],
                row["side"],
                "open",
                row["opened_at"],
                row["entry_price"],
                row["qty"],
                row.get("margin"),
                row["leverage"],
                row["stop_price"],
                row["best_price"],
                row["worst_price"],
                row.get("max_roe", 0.0),
                row.get("min_roe", 0.0),
                row.get("entry_order_id"),
                row.get("last_exchange_stop"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)

    def update_open(self, conn: sqlite3.Connection, trade_id: int, fields: dict[str, Any]) -> None:
        allowed = {
            "stop_price",
            "best_price",
            "worst_price",
            "max_roe",
            "min_roe",
            "last_exchange_stop",
            "margin",
            "entry_price",
            "qty",
            "profit_lock_armed",
            "locked_stop_roe",
        }
        parts = []
        vals: list[Any] = []
        for k, v in fields.items():
            if k in allowed:
                parts.append(f"{k}=?")
                vals.append(v)
        if not parts:
            return
        vals.append(trade_id)
        conn.execute(f"UPDATE em6_bybit_trades SET {', '.join(parts)} WHERE id=?", vals)
        conn.commit()

    def close_trade(self, conn: sqlite3.Connection, trade_id: int, fields: dict[str, Any]) -> None:
        conn.execute(
            """
            UPDATE em6_bybit_trades SET
                status='closed', closed_at=?, exit_price=?, exit_reason=?,
                pnl_usd=?, roe_pct=?, max_roe=?, min_roe=?, stop_price=?,
                best_price=?, worst_price=?, exit_json=?
            WHERE id=?
            """,
            (
                fields.get("closed_at"),
                fields.get("exit_price"),
                fields.get("exit_reason"),
                fields.get("pnl_usd"),
                fields.get("roe_pct"),
                fields.get("max_roe"),
                fields.get("min_roe"),
                fields.get("stop_price"),
                fields.get("best_price"),
                fields.get("worst_price"),
                json.dumps(fields.get("exit_json") or {}, ensure_ascii=False),
                trade_id,
            ),
        )
        conn.commit()

    def list_trades(
        self, conn: sqlite3.Connection, status: str | None, limit: int = 500
    ) -> list[dict[str, Any]]:
        if status:
            rows = conn.execute(
                """
                SELECT * FROM em6_bybit_trades WHERE status=? ORDER BY opened_at DESC LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM em6_bybit_trades ORDER BY opened_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def open_by_symbol(self, conn: sqlite3.Connection, symbol: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM em6_bybit_trades WHERE status='open' AND symbol=? LIMIT 1",
            (symbol,),
        ).fetchone()
        return dict(row) if row else None

    def all_open(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM em6_bybit_trades WHERE status='open' ORDER BY opened_at"
        ).fetchall()
        return [dict(r) for r in rows]
