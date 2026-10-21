"""Вкладка EMA6 Bybit: снимок из Redis или SQLite."""

from __future__ import annotations

from typing import Any

import config
from signal_engine.live.em6_bybit.store import Em6BybitStore


class Em6BybitCache:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    def apply(self, envelope: dict[str, Any]) -> bool:
        if envelope.get("type") != "em6_bybit":
            return False
        data = envelope.get("data")
        if isinstance(data, dict):
            self.payload = data
        return True

    def view(self) -> dict[str, Any] | None:
        return self.payload


def snapshot_from_db() -> dict[str, Any]:
    store = Em6BybitStore()
    conn = store.open()
    try:
        closed = store.list_trades(conn, "closed", 200)
        open_rows = store.list_trades(conn, "open", 50)
        wins = sum(1 for r in closed if float(r.get("pnl_usd") or 0) > 0)
        n = len(closed)
        pnl = sum(float(r.get("pnl_usd") or 0) for r in closed)
        return {
            "summary": {
                "label": "EMA6 Bybit Demo",
                "wallet_equity": 0.0,
                "wallet_available": 0.0,
                "margin_pct": config.PAPER_MARGIN_PCT,
                "leverage": config.PAPER_LEVERAGE,
                "open_trades": len(open_rows),
                "closed_trades": n,
                "win_rate": round(100.0 * wins / n, 1) if n else 0.0,
                "total_pnl_closed": round(pnl, 2),
            },
            "open_trades": open_rows,
            "closed_trades": closed,
        }
    finally:
        conn.close()
