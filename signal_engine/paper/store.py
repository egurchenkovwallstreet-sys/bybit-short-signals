"""SQLite теста стратегии: сделки, кандидаты (с теневыми сделками), баланс, лента."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    candidate_id INTEGER,
    kind TEXT,
    status TEXT NOT NULL,
    opened_at INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    margin REAL NOT NULL,
    leverage INTEGER NOT NULL,
    notional REAL NOT NULL,
    qty REAL NOT NULL,
    liq_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    best_price REAL NOT NULL,
    worst_price REAL NOT NULL,
    last_price REAL,
    entry_fee REAL NOT NULL,
    funding_paid REAL NOT NULL DEFAULT 0,
    next_funding_ts INTEGER,
    score REAL,
    grade TEXT,
    strict_btc INTEGER,
    balance_before REAL,
    entry_json TEXT,
    closed_at INTEGER,
    exit_price REAL,
    exit_reason TEXT,
    exit_fee REAL,
    pnl_usd REAL,
    roe_pct REAL,
    max_roe REAL,
    min_roe REAL,
    balance_after REAL,
    exit_json TEXT
);
CREATE INDEX IF NOT EXISTS paper_trades_status ON paper_trades(status);
CREATE INDEX IF NOT EXISTS paper_trades_symbol ON paper_trades(symbol, closed_at);

CREATE TABLE IF NOT EXISTS paper_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    kind TEXT,
    status TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    ended_at INTEGER,
    end_reason TEXT,
    peak_price REAL,
    peak_ts INTEGER,
    valley_price REAL,
    valley_ts INTEGER,
    growth_pct REAL,
    scans INTEGER NOT NULL DEFAULT 0,
    fail_counts TEXT,
    best_passed INTEGER NOT NULL DEFAULT 0,
    last_eval TEXT,
    trade_id INTEGER,
    near_miss_at INTEGER,
    near_miss_missing TEXT,
    near_miss_json TEXT,
    shadow_status TEXT,
    shadow_entry_price REAL,
    shadow_opened_at INTEGER,
    shadow_stop REAL,
    shadow_best REAL,
    shadow_worst REAL,
    shadow_liq REAL,
    shadow_entry_fee REAL,
    shadow_margin REAL,
    shadow_closed_at INTEGER,
    shadow_exit_price REAL,
    shadow_exit_reason TEXT,
    shadow_pnl_usd REAL,
    shadow_roe REAL,
    shadow_max_roe REAL
);
CREATE INDEX IF NOT EXISTS paper_candidates_status ON paper_candidates(status);
CREATE INDEX IF NOT EXISTS paper_candidates_shadow ON paper_candidates(shadow_status);

CREATE TABLE IF NOT EXISTS paper_equity (
    ts INTEGER PRIMARY KEY,
    balance REAL NOT NULL,
    equity REAL NOT NULL,
    open_trades INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_tape (
    symbol TEXT NOT NULL,
    ts INTEGER NOT NULL,
    buy REAL NOT NULL,
    sell REAL NOT NULL,
    PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS paper_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class PaperStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    @property
    def db(self) -> sqlite3.Connection:
        assert self.conn is not None, "PaperStore не открыт"
        return self.conn

    # --- kv ---

    def get_kv(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM paper_kv WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set_kv(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO paper_kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.db.commit()

    # --- сделки ---

    def insert_trade(self, row: dict[str, Any]) -> int:
        keys = list(row)
        cur = self.db.execute(
            f"INSERT INTO paper_trades({', '.join(keys)}) VALUES({', '.join('?' for _ in keys)})",
            [_encode(row[k]) for k in keys],
        )
        self.db.commit()
        return int(cur.lastrowid)

    def update_trade(self, trade_id: int, fields: dict[str, Any], commit: bool = True) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(
            f"UPDATE paper_trades SET {sets} WHERE id = ?",
            [_encode(v) for v in fields.values()] + [trade_id],
        )
        if commit:
            self.db.commit()

    def open_trades(self) -> list[sqlite3.Row]:
        return list(self.db.execute("SELECT * FROM paper_trades WHERE status = 'open' ORDER BY opened_at"))

    def last_close_by_symbol(self) -> dict[str, int]:
        rows = self.db.execute(
            "SELECT symbol, MAX(closed_at) AS ts FROM paper_trades WHERE status = 'closed' GROUP BY symbol"
        )
        return {str(r["symbol"]): int(r["ts"]) for r in rows if r["ts"] is not None}

    # --- кандидаты ---

    def insert_candidate(self, row: dict[str, Any]) -> int:
        keys = list(row)
        cur = self.db.execute(
            f"INSERT INTO paper_candidates({', '.join(keys)}) VALUES({', '.join('?' for _ in keys)})",
            [_encode(row[k]) for k in keys],
        )
        self.db.commit()
        return int(cur.lastrowid)

    def update_candidate(self, cand_id: int, fields: dict[str, Any], commit: bool = True) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(
            f"UPDATE paper_candidates SET {sets} WHERE id = ?",
            [_encode(v) for v in fields.values()] + [cand_id],
        )
        if commit:
            self.db.commit()

    def active_candidates(self) -> list[sqlite3.Row]:
        return list(self.db.execute("SELECT * FROM paper_candidates WHERE status = 'watching'"))

    def open_shadows(self) -> list[sqlite3.Row]:
        return list(self.db.execute("SELECT * FROM paper_candidates WHERE shadow_status = 'open'"))

    def last_peak_by_symbol(self) -> dict[str, int]:
        rows = self.db.execute(
            "SELECT symbol, MAX(peak_ts) AS ts FROM paper_candidates WHERE status != 'watching' GROUP BY symbol"
        )
        return {str(r["symbol"]): int(r["ts"]) for r in rows if r["ts"] is not None}

    # --- баланс ---

    def add_equity(self, ts: int, balance: float, equity: float, open_trades: int) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO paper_equity(ts, balance, equity, open_trades) VALUES(?, ?, ?, ?)",
            (ts, balance, equity, open_trades),
        )
        self.db.commit()

    # --- лента ---

    def save_tape(self, rows: list[tuple[str, int, float, float]], cutoff_ts: int) -> None:
        if rows:
            self.db.executemany(
                "INSERT OR REPLACE INTO paper_tape(symbol, ts, buy, sell) VALUES(?, ?, ?, ?)", rows
            )
        self.db.execute("DELETE FROM paper_tape WHERE ts < ?", (cutoff_ts,))
        self.db.commit()

    def load_tape(self, cutoff_ts: int) -> list[sqlite3.Row]:
        return list(self.db.execute("SELECT symbol, ts, buy, sell FROM paper_tape WHERE ts >= ?", (cutoff_ts,)))

    def commit(self) -> None:
        self.db.commit()


def _encode(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=_json_default)
    if isinstance(value, bool):
        return int(value)
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, float):
        return None
    return str(value)
