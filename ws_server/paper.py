"""Тест стратегии в веб-сервере: живой снимок из Redis и чтение журнала SQLite."""

from __future__ import annotations

import sqlite3
from typing import Any

import config
from signal_engine.paper.analytics import compute_analytics, list_candidates, list_trades
from signal_engine.paper.detect import VARIANT_LABELS


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


def _summary_accounts_from_analytics(analytics: dict[str, Any]) -> dict[str, dict[str, Any]]:
    accounts: dict[str, dict[str, Any]] = {}
    by_variant = (analytics.get("variants") or {}) if analytics else {}
    for variant in config.PAPER_VARIANTS:
        trades = (by_variant.get(variant) or {}).get("trades") or {}
        balance = trades.get("balance")
        if balance is None:
            balance = config.PAPER_START_BALANCE_USD
        balance = float(balance)
        open_n = int(trades.get("open") or 0)
        accounts[variant] = {
            "label": VARIANT_LABELS.get(variant, variant),
            "balance": round(balance, 2),
            "equity": round(balance, 2),
            "unrealized": 0.0,
            "used_margin": 0.0,
            "free_margin": round(balance, 2),
            "open_trades": open_n,
        }
    return accounts


def snapshot_from_db() -> dict[str, Any]:
    conn = _connect()
    if conn is None:
        return {"summary": None, "open_trades": [], "candidates": [], "analytics": {}}
    try:
        open_rows = list_trades(conn, "open", 500)
        analytics = compute_analytics(conn)
        accounts = _summary_accounts_from_analytics(analytics)
        return {
            "summary": {
                "start_balance": config.PAPER_START_BALANCE_USD,
                "accounts": accounts,
                "candidates": 0,
                "shadows_open": 0,
                "btc_4h_pct": None,
                "btc_strict": False,
                "margin_pct": config.PAPER_MARGIN_PCT,
                "leverage": config.PAPER_LEVERAGE,
                "fee_rate": config.PAPER_FEE_RATE_TAKER,
            },
            "open_trades": open_rows,
            "candidates": [],
            "analytics": analytics,
            "desk_variants": list(config.PAPER_DESK_VARIANTS),
        }
    finally:
        conn.close()


def trades(
    status: str, limit: int, variant: str | None = None, symbol: str | None = None
) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    try:
        return list_trades(conn, status, limit, variant, symbol)
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


def request_manual_close(trade_id: int) -> bool:
    from signal_engine.paper.store import PaperStore

    store = PaperStore(config.PAPER_SQLITE_PATH)
    store.open()
    try:
        if not store.trade_is_open(trade_id):
            return False
        store.enqueue_manual_close(trade_id)
        return True
    finally:
        store.close()
