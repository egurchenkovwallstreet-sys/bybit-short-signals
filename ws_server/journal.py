"""Журнал сигналов для вкладки «не отработанные»."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


def list_unprocessed(path: Path | str, *, recent_hours: int = 168, limit: int = 200) -> list[dict[str, Any]]:
    """Открытые + недавно закрытые до 5/5 (не «отработаны» до входа)."""
    database = Path(path)
    if not database.is_file():
        return []
    cutoff = int(time.time() * 1000) - recent_hours * 3600 * 1000
    try:
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, symbol, created_at, updated_at, entry_price, last_price,
                   strength, rating, probability, status, label, outcome, exit_at, pnl_pct,
                   price_change_5m, price_change_15m
            FROM signals
            WHERE outcome IS NULL
               OR (
                    outcome IS NOT NULL
                    AND strength < 5
                    AND COALESCE(exit_at, updated_at) >= ?
                  )
            ORDER BY COALESCE(exit_at, updated_at) DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [dict(row) for row in rows]
