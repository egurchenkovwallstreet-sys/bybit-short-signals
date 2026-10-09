"""SQLite лаборатории пампа."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    pump_class TEXT NOT NULL,
    phase TEXT NOT NULL,
    status TEXT NOT NULL,
    valley_price REAL,
    valley_ts INTEGER,
    peak_price REAL,
    peak_ts INTEGER,
    growth_pct REAL,
    started_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    ended_at INTEGER,
    end_reason TEXT,
    phase_since INTEGER,
    last_price REAL,
    drawdown_pct REAL,
    metrics_json TEXT
);
CREATE INDEX IF NOT EXISTS lab_episodes_status ON lab_episodes(status, pump_class);
CREATE INDEX IF NOT EXISTS lab_episodes_symbol ON lab_episodes(symbol, status);

CREATE TABLE IF NOT EXISTS lab_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    phase TEXT NOT NULL,
    price REAL,
    drawdown_pct REAL,
    metrics_json TEXT NOT NULL,
    FOREIGN KEY (episode_id) REFERENCES lab_episodes(id)
);
CREATE INDEX IF NOT EXISTS lab_snapshots_ep ON lab_snapshots(episode_id, ts);

CREATE TABLE IF NOT EXISTS lab_metric_series (
    episode_id INTEGER NOT NULL,
    metric_id TEXT NOT NULL,
    horizon TEXT NOT NULL,
    ts INTEGER NOT NULL,
    value REAL,
    PRIMARY KEY (episode_id, metric_id, horizon, ts)
);
CREATE INDEX IF NOT EXISTS lab_metric_series_ep ON lab_metric_series(episode_id, metric_id);
"""


class PumpLabStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("PumpLabStore не открыт")
        return self._conn

    def active_episodes(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM lab_episodes WHERE status = 'active' ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def active_by_symbol(self) -> dict[str, dict[str, Any]]:
        return {row["symbol"]: row for row in self.active_episodes()}

    def active_by_symbol_class(self) -> dict[tuple[str, str], dict[str, Any]]:
        return {(row["symbol"], row["pump_class"]): row for row in self.active_episodes()}

    def insert_episode(self, row: dict[str, Any]) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO lab_episodes (
                symbol, pump_class, phase, status, valley_price, valley_ts,
                peak_price, peak_ts, growth_pct, started_at, updated_at,
                phase_since, last_price, drawdown_pct, metrics_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["symbol"],
                row["pump_class"],
                row["phase"],
                "active",
                row.get("valley_price"),
                row.get("valley_ts"),
                row.get("peak_price"),
                row.get("peak_ts"),
                row.get("growth_pct"),
                row["started_at"],
                row["updated_at"],
                row.get("phase_since", row["started_at"]),
                row.get("last_price"),
                row.get("drawdown_pct"),
                json.dumps(row.get("metrics") or {}, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_episode(self, episode_id: int, row: dict[str, Any]) -> None:
        self.conn.execute(
            """
            UPDATE lab_episodes SET
                pump_class = ?, phase = ?, updated_at = ?, peak_price = ?, peak_ts = ?,
                growth_pct = ?, phase_since = ?, last_price = ?, drawdown_pct = ?,
                metrics_json = ?, valley_price = ?, valley_ts = ?
            WHERE id = ?
            """,
            (
                row["pump_class"],
                row["phase"],
                row["updated_at"],
                row.get("peak_price"),
                row.get("peak_ts"),
                row.get("growth_pct"),
                row.get("phase_since"),
                row.get("last_price"),
                row.get("drawdown_pct"),
                json.dumps(row.get("metrics") or {}, ensure_ascii=False),
                row.get("valley_price"),
                row.get("valley_ts"),
                episode_id,
            ),
        )
        self.conn.commit()

    def close_episode(self, episode_id: int, now_ms: int, reason: str) -> None:
        self.conn.execute(
            """
            UPDATE lab_episodes SET status = 'closed', ended_at = ?, end_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (now_ms, reason, now_ms, episode_id),
        )
        self.conn.commit()

    def insert_snapshot(self, episode_id: int, ts: int, phase: str, price: float | None, dd: float | None, metrics: dict) -> None:
        self.conn.execute(
            """
            INSERT INTO lab_snapshots (episode_id, ts, phase, price, drawdown_pct, metrics_json)
            VALUES (?,?,?,?,?,?)
            """,
            (episode_id, ts, phase, price, dd, json.dumps(metrics, ensure_ascii=False)),
        )
        self.conn.commit()

    def append_metric_points(self, episode_id: int, ts: int, metrics: dict[str, dict]) -> None:
        for metric_id, horizons in metrics.items():
            if not isinstance(horizons, dict):
                continue
            for horizon, cell in horizons.items():
                if horizon not in ("short", "mid", "long"):
                    continue
                val = cell.get("value") if isinstance(cell, dict) else None
                if val is None:
                    continue
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO lab_metric_series (episode_id, metric_id, horizon, ts, value)
                    VALUES (?,?,?,?,?)
                    """,
                    (episode_id, metric_id, horizon, ts, float(val)),
                )
        self.conn.commit()
        self._trim_series(episode_id)

    def _trim_series(self, episode_id: int) -> None:
        import config

        limit = config.PUMP_LAB_HISTORY_POINTS
        for metric_id, horizon in self.conn.execute(
            "SELECT DISTINCT metric_id, horizon FROM lab_metric_series WHERE episode_id = ?",
            (episode_id,),
        ):
            rows = self.conn.execute(
                """
                SELECT ts FROM lab_metric_series
                WHERE episode_id = ? AND metric_id = ? AND horizon = ?
                ORDER BY ts DESC
                """,
                (episode_id, metric_id, horizon),
            ).fetchall()
            if len(rows) <= limit:
                continue
            cutoff = rows[limit - 1][0]
            self.conn.execute(
                """
                DELETE FROM lab_metric_series
                WHERE episode_id = ? AND metric_id = ? AND horizon = ? AND ts < ?
                """,
                (episode_id, metric_id, horizon, cutoff),
            )
        self.conn.commit()

    def metric_history(self, episode_id: int, metric_id: str, horizon: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT ts, value FROM lab_metric_series
            WHERE episode_id = ? AND metric_id = ? AND horizon = ?
            ORDER BY ts ASC
            """,
            (episode_id, metric_id, horizon),
        ).fetchall()
        return [{"ts": r[0], "value": r[1]} for r in rows]

    def episode(self, episode_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM lab_episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["metrics"] = json.loads(data.pop("metrics_json") or "{}")
        return data

    def recent_snapshots(self, episode_id: int, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT ts, phase, price, drawdown_pct, metrics_json
            FROM lab_snapshots WHERE episode_id = ?
            ORDER BY ts DESC LIMIT ?
            """,
            (episode_id, limit),
        ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "ts": r[0],
                    "phase": r[1],
                    "price": r[2],
                    "drawdown_pct": r[3],
                    "metrics": json.loads(r[4] or "{}"),
                }
            )
        return out
