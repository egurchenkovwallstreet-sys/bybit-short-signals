"""Закрытые сделки EMA6: на дашборде — только closed PnL с Bybit Demo API."""

from __future__ import annotations

import logging
import time
from typing import Any

import config
from signal_engine.live.em6_bybit.broker import Em6BybitBroker
from signal_engine.live.em6_bybit.store import Em6BybitStore

log = logging.getLogger(__name__)

_closed_cache: dict[str, Any] = {"at": 0.0, "rows": []}


def invalidate_closed_cache() -> None:
    _closed_cache["at"] = 0.0
    _closed_cache["rows"] = []


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


def journal_symbol_hints(*, limit: int = 500) -> list[str]:
    """Символы из журнала em6 (открытые и закрытые) — не вся история Demo."""
    try:
        store = Em6BybitStore()
        conn = store.open()
        try:
            rows = store.list_trades(conn, None, limit)
            return sorted(
                {str(r.get("symbol") or "") for r in rows if r.get("symbol")}
            )
        finally:
            conn.close()
    except Exception:
        log.exception("em6 bybit: journal symbols")
        return []


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
    """Дубликат по ключу: биржа перекрывает журнал (тесты / legacy)."""
    merged: dict[str, dict[str, Any]] = {}
    for row in journal:
        merged[_closed_key(row)] = row
    for row in exchange:
        merged[_closed_key(row)] = row
    out = list(merged.values())
    out.sort(key=lambda r: int(r.get("closed_at") or 0), reverse=True)
    return out


def _journal_matches_exchange(j: dict[str, Any], ex: dict[str, Any]) -> bool:
    if str(j.get("symbol")) != str(ex.get("symbol")):
        return False
    ent_j = float(j.get("entry_price") or 0)
    ent_e = float(ex.get("entry_price") or 0)
    if ent_e <= 0 or ent_j <= 0:
        return False
    if abs(ent_j - ent_e) / ent_e > 0.025:
        return False
    jc = int(j.get("closed_at") or 0)
    ec = int(ex.get("closed_at") or 0)
    if jc and ec and abs(jc - ec) > 900_000:
        return False
    return True


def enrich_exchange_with_journal(
    exchange: list[dict[str, Any]], journal: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """PnL/цены с биржи; exit_reason из журнала бота, если сопоставилось."""
    if not journal:
        return exchange
    used: set[int] = set()
    out: list[dict[str, Any]] = []
    for ex in exchange:
        row = dict(ex)
        for i, j in enumerate(journal):
            if i in used:
                continue
            if _journal_matches_exchange(j, ex):
                reason = str(j.get("exit_reason") or "").strip()
                if reason and reason not in ("journal", "exchange"):
                    row["exit_reason"] = reason
                used.add(i)
                break
        out.append(row)
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
    start_days: int = 7,
) -> list[dict[str, Any]]:
    """Список закрытых и статистика — только get_closed_pnl (Demo), журнал не подмешивается."""
    del symbol_hints  # полная история счёта linear, как в Bybit
    lim = min(max(1, limit), 500)
    journal = journal_closed_rows(limit=lim)
    if not broker.configured():
        return journal[:lim]

    cache_sec = float(config.EM6_BYBIT_CLOSED_CACHE_SEC)
    now = time.time()
    if (
        _closed_cache["rows"]
        and now - float(_closed_cache["at"]) < cache_sec
    ):
        return list(_closed_cache["rows"])[:lim]

    start_ms = int(time.time() * 1000) - start_days * 86400 * 1000
    exchange: list[dict[str, Any]] = []
    try:
        exchange = broker.list_recent_closed_pnl(
            start_ms=start_ms,
            limit=lim,
            symbols=None,
        )
    except Exception:
        log.exception("em6 bybit: exchange closed pnl")

    if exchange:
        closed = enrich_exchange_with_journal(exchange, journal)[:lim]
        _closed_cache["at"] = now
        _closed_cache["rows"] = closed
        return closed

    _closed_cache["at"] = now
    _closed_cache["rows"] = []
    return []
