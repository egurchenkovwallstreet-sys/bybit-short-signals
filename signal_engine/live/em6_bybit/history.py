"""Закрытые сделки EMA6: журнал SQLite + Bybit closed PnL."""

from __future__ import annotations

import logging
import time
from typing import Any

from signal_engine.live.em6_bybit.broker import Em6BybitBroker
from signal_engine.live.em6_bybit.store import Em6BybitStore

log = logging.getLogger(__name__)


def normalize_journal_closed(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(row.get("symbol") or ""),
        "side": str(row.get("side") or ""),
        "entry_price": float(row.get("entry_price") or 0),
        "exit_price": float(row.get("exit_price") or 0),
        "pnl_usd": round(float(row.get("pnl_usd") or 0), 4),
        "roe_pct": round(float(row.get("roe_pct") or 0), 2),
        "closed_at": int(row.get("closed_at") or 0),
        "exit_reason": str(row.get("exit_reason") or "journal"),
        "source": "local",
    }


def journal_closed_rows(*, limit: int = 200) -> list[dict[str, Any]]:
    try:
        store = Em6BybitStore()
        conn = store.open()
        try:
            raw = store.list_trades(conn, "closed", limit)
            return [normalize_journal_closed(dict(r)) for r in raw]
        finally:
            conn.close()
    except Exception:
        log.exception("em6 bybit: journal closed")
        return []


def _closed_key(row: dict[str, Any]) -> str:
    return (
        f"{row.get('symbol')}|{row.get('closed_at')}|"
        f"{row.get('entry_price')}|{row.get('pnl_usd')}"
    )


def merge_closed_rows(
    exchange: list[dict[str, Any]], journal: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in journal:
        merged[_closed_key(row)] = row
    for row in exchange:
        merged[_closed_key(row)] = row
    out = list(merged.values())
    out.sort(key=lambda r: int(r.get("closed_at") or 0), reverse=True)
    return out


def summary_from_closed(closed: list[dict[str, Any]]) -> dict[str, float | int]:
    n = len(closed)
    wins = sum(1 for r in closed if float(r.get("pnl_usd") or 0) > 0)
    pnl = sum(float(r.get("pnl_usd") or 0) for r in closed)
    return {
        "closed_trades": n,
        "win_rate": round(100.0 * wins / n, 1) if n else 0.0,
        "total_pnl_closed": round(pnl, 2),
    }


def load_closed_for_dashboard(
    broker: Em6BybitBroker,
    *,
    symbol_hints: list[str] | None = None,
    limit: int = 200,
    start_days: int = 90,
) -> list[dict[str, Any]]:
    journal = journal_closed_rows(limit=limit)
    hints: set[str] = {s for s in (symbol_hints or []) if s}
    for row in journal:
        sym = str(row.get("symbol") or "")
        if sym:
            hints.add(sym)
    exchange: list[dict[str, Any]] = []
    if broker.configured():
        start_ms = int(time.time() * 1000) - start_days * 86400 * 1000
        try:
            exchange = broker.list_recent_closed_pnl(
                start_ms=start_ms,
                limit=min(limit, 100),
                symbols=sorted(hints) if hints else None,
            )
        except Exception:
            log.exception("em6 bybit: exchange closed pnl")
    return merge_closed_rows(exchange, journal)
