"""Тест стратегии в веб-сервере: живой снимок из Redis и чтение журнала SQLite."""

from __future__ import annotations

import sqlite3
from typing import Any

import config
from signal_engine.paper.analytics import compute_analytics, list_candidates, list_trades


class PaperCache:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    def apply(self, envelope: dict[str, Any]) -> bool:
        if envelope.get("type") != "paper_test":
            return False
        data = envelope.get("data")
        if isinstance(data, dict):
            self.payload = data
        return True

    def view(self) -> dict[str, Any] | None:
        return self.payload


def _connect() -> sqlite3.Connection | None:
    path = config.PAPER_SQLITE_PATH
    if not path.is_file():
        return None
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def snapshot_from_db() -> dict[str, Any]:
    conn = _connect()
    if conn is None:
        return {"summary": None, "open_trades": [], "candidates": [], "analytics": {}}
    try:
        return {"summary": None, "open_trades": [], "candidates": [], "analytics": compute_analytics(conn)}
    finally:
        conn.close()


def trades(status: str, limit: int, variant: str | None = None) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    try:
        return list_trades(conn, status, limit, variant)
    finally:
        conn.close()


def candidates(limit: int) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    try:
        return list_candidates(conn, limit)
    finally:
        conn.close()
