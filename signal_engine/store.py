"""Журнал сигналов в SQLite. Одна открытая карточка на символ."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from signal_engine.models import Signal


_COLUMNS = (
    "symbol",
    "created_at",
    "updated_at",
    "entry_price",
    "last_price",
    "strength",
    "rating",
    "probability",
    "quality",
    "tf_match",
    "extra",
    "color",
    "status",
    "label",
    "price_change_5m",
    "price_change_15m",
    "volume_ratio",
    "rsi",
    "liquidations_faded",
    "oi_drop",
    "oi_change_pct",
    "volume_faded",
    "sweep",
    "sweep_timeframes",
    "mega_level",
    "round_level",
    "cvd_divergence",
    "taker_ratio",
    "obv_divergence",
    "funding_rate",
    "outcome",
    "exit_price",
    "exit_at",
    "pnl_pct",
)


class SignalStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                last_price REAL,
                strength INTEGER NOT NULL,
                rating REAL NOT NULL,
                probability REAL NOT NULL,
                quality REAL NOT NULL,
                tf_match INTEGER NOT NULL,
                extra INTEGER NOT NULL,
                color TEXT NOT NULL,
                status TEXT NOT NULL,
                label TEXT NOT NULL,
                price_change_5m REAL,
                price_change_15m REAL,
                volume_ratio REAL,
                rsi REAL,
                liquidations_faded INTEGER NOT NULL,
                oi_drop INTEGER NOT NULL,
                oi_change_pct REAL,
                volume_faded INTEGER NOT NULL,
                sweep INTEGER NOT NULL,
                sweep_timeframes TEXT,
                mega_level INTEGER NOT NULL,
                round_level INTEGER NOT NULL,
                cvd_divergence INTEGER NOT NULL,
                taker_ratio REAL,
                obv_divergence INTEGER NOT NULL,
                funding_rate REAL,
                outcome TEXT,
                exit_price REAL,
                exit_at INTEGER,
                pnl_pct REAL
            )
            """
        )
        self._conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_one_open
            ON signals(symbol) WHERE outcome IS NULL
            """
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def insert(self, signal: Signal) -> int:
        values = _values(signal)
        columns = ", ".join(_COLUMNS)
        marks = ", ".join("?" for _ in _COLUMNS)
        cursor = self._connection().execute(
            f"INSERT INTO signals ({columns}) VALUES ({marks})",
            values,
        )
        self._connection().commit()
        signal.id = int(cursor.lastrowid)
        return signal.id

    def update(self, signal: Signal) -> None:
        if signal.id is None:
            raise ValueError("у сигнала нет id")
        assignments = ", ".join(f"{name} = ?" for name in _COLUMNS)
        self._connection().execute(
            f"UPDATE signals SET {assignments} WHERE id = ?",
            [*_values(signal), signal.id],
        )
        self._connection().commit()

    def load_open(self) -> list[Signal]:
        rows = self._connection().execute(
            "SELECT * FROM signals WHERE outcome IS NULL ORDER BY id"
        ).fetchall()
        return [_from_row(row) for row in rows]

    def outcome_counts(self) -> tuple[int, int]:
        """Победы (TP_HIT) и число всех закрытых сигналов."""
        row = self._connection().execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN outcome = 'TP_HIT' THEN 1 ELSE 0 END), 0) AS wins,
                COUNT(*) AS total
            FROM signals
            WHERE outcome IS NOT NULL
            """
        ).fetchone()
        return int(row["wins"]), int(row["total"])

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("база сигналов не открыта")
        return self._conn


def _values(signal: Signal) -> list:
    timeframes = ",".join(signal.sweep_timeframes)
    return [
        signal.symbol,
        signal.created_at,
        signal.updated_at,
        signal.entry_price,
        signal.last_price,
        signal.strength,
        signal.rating,
        signal.probability,
        signal.quality,
        signal.tf_match,
        signal.extra,
        signal.color,
        signal.status,
        signal.label,
        signal.price_change_5m,
        signal.price_change_15m,
        signal.volume_ratio,
        signal.rsi,
        int(signal.liquidations_faded),
        int(signal.oi_drop),
        signal.oi_change_pct,
        int(signal.volume_faded),
        int(signal.sweep),
        timeframes,
        int(signal.mega_level),
        int(signal.round_level),
        int(signal.cvd_divergence),
        signal.taker_ratio,
        int(signal.obv_divergence),
        signal.funding_rate,
        signal.outcome,
        signal.exit_price,
        signal.exit_at,
        signal.pnl_pct,
    ]


def _from_row(row: sqlite3.Row) -> Signal:
    raw_tf = row["sweep_timeframes"] or ""
    timeframes = [item for item in raw_tf.split(",") if item]
    return Signal(
        id=int(row["id"]),
        symbol=row["symbol"],
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
        entry_price=float(row["entry_price"]),
        last_price=float(row["last_price"] if row["last_price"] is not None else row["entry_price"]),
        strength=int(row["strength"]),
        rating=float(row["rating"]),
        probability=float(row["probability"]),
        quality=float(row["quality"]),
        tf_match=int(row["tf_match"]),
        extra=int(row["extra"]),
        color=row["color"],
        status=row["status"],
        label=row["label"],
        price_change_5m=row["price_change_5m"],
        price_change_15m=row["price_change_15m"],
        volume_ratio=row["volume_ratio"],
        rsi=row["rsi"],
        liquidations_faded=bool(row["liquidations_faded"]),
        oi_drop=bool(row["oi_drop"]),
        oi_change_pct=row["oi_change_pct"],
        volume_faded=bool(row["volume_faded"]),
        sweep=bool(row["sweep"]),
        sweep_timeframes=timeframes,
        mega_level=bool(row["mega_level"]),
        round_level=bool(row["round_level"]),
        cvd_divergence=bool(row["cvd_divergence"]),
        taker_ratio=row["taker_ratio"],
        obv_divergence=bool(row["obv_divergence"]),
        funding_rate=row["funding_rate"],
        outcome=row["outcome"],
        exit_price=row["exit_price"],
        exit_at=row["exit_at"],
        pnl_pct=row["pnl_pct"],
    )
