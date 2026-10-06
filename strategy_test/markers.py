"""Маркеры входа на графике — из журнала SQLite."""

from __future__ import annotations

from typing import Any


def markers_from_signals(rows: list[dict[str, Any]], limit: int = 120) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        entry_ts = int(row.get("entry_ts") or 0)
        if entry_ts <= 0:
            continue
        out.append(
            {
                "time": entry_ts // 1000,
                "side": str(row.get("side") or ""),
                "grade": str(row.get("grade") or ""),
                "mode": str(row.get("mode") or ""),
                "price": float(row.get("entry_price") or 0),
                "signal_id": int(row.get("id") or 0),
                "open": row.get("exit_ts") is None,
            }
        )
    return out
