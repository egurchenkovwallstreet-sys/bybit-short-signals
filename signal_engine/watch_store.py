"""Липкий список монет на досках памп-скан и 2× откат (SQLite)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class WatchRow:
    board: str
    symbol: str
    entered_at: int
    dismissed: bool
    confirmed_stage: int
    pending_stage: int | None
    pending_since: int | None
    meta: dict[str, Any]

    def to_meta_json(self) -> str:
        return json.dumps(self.meta, separators=(",", ":"))


class WatchStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS board_watches (
                board TEXT NOT NULL,
                symbol TEXT NOT NULL,
                entered_at INTEGER NOT NULL,
                dismissed INTEGER NOT NULL DEFAULT 0,
                confirmed_stage INTEGER NOT NULL DEFAULT 1,
                pending_stage INTEGER,
                pending_since INTEGER,
                meta_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (board, symbol)
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def active(self, board: str) -> dict[str, WatchRow]:
        self._ensure()
        rows = self._conn.execute(
            "SELECT * FROM board_watches WHERE board = ? AND dismissed = 0",
            (board,),
        ).fetchall()
        out: dict[str, WatchRow] = {}
        for row in rows:
            out[str(row["symbol"])] = _row_to_watch(row)
        return out

    def get(self, board: str, symbol: str) -> WatchRow | None:
        self._ensure()
        row = self._conn.execute(
            "SELECT * FROM board_watches WHERE board = ? AND symbol = ?",
            (board, symbol),
        ).fetchone()
        return _row_to_watch(row) if row else None

    def upsert(self, watch: WatchRow) -> None:
        self._ensure()
        self._conn.execute(
            """
            INSERT INTO board_watches (
                board, symbol, entered_at, dismissed, confirmed_stage,
                pending_stage, pending_since, meta_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(board, symbol) DO UPDATE SET
                dismissed = excluded.dismissed,
                confirmed_stage = excluded.confirmed_stage,
                pending_stage = excluded.pending_stage,
                pending_since = excluded.pending_since,
                meta_json = excluded.meta_json
            """,
            (
                watch.board,
                watch.symbol,
                watch.entered_at,
                1 if watch.dismissed else 0,
                watch.confirmed_stage,
                watch.pending_stage,
                watch.pending_since,
                watch.to_meta_json(),
            ),
        )
        self._conn.commit()

    def dismiss(self, board: str, symbol: str) -> None:
        self._ensure()
        self._conn.execute(
            """
            UPDATE board_watches SET dismissed = 1
            WHERE board = ? AND symbol = ?
            """,
            (board, symbol),
        )
        self._conn.commit()

    def remove(self, board: str, symbol: str) -> None:
        self._ensure()
        self._conn.execute("DELETE FROM board_watches WHERE board = ? AND symbol = ?", (board, symbol))
        self._conn.commit()

    def _ensure(self) -> None:
        if self._conn is None:
            self.open()


def _row_to_watch(row: sqlite3.Row) -> WatchRow:
    meta_raw = row["meta_json"] or "{}"
    try:
        meta = json.loads(meta_raw)
    except json.JSONDecodeError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return WatchRow(
        board=str(row["board"]),
        symbol=str(row["symbol"]),
        entered_at=int(row["entered_at"]),
        dismissed=bool(row["dismissed"]),
        confirmed_stage=int(row["confirmed_stage"]),
        pending_stage=int(row["pending_stage"]) if row["pending_stage"] is not None else None,
        pending_since=int(row["pending_since"]) if row["pending_since"] is not None else None,
        meta=meta,
    )


def growth_pct_negative(state) -> bool:
    from signal_engine.pump_scan import price_24h_pct

    pct = price_24h_pct(state.price_24h_change)
    return pct is not None and pct < 0
