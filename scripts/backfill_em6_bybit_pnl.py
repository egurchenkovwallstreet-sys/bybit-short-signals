#!/usr/bin/env python3
"""Подтянуть closed PnL с Bybit для em6_bybit_trades с pnl_usd=0."""
from __future__ import annotations

import sqlite3

import config
from signal_engine.live.em6_bybit.broker import Em6BybitBroker
from signal_engine.live.em6_bybit.store import Em6BybitStore


def main() -> None:
    broker = Em6BybitBroker()
    if not broker.configured():
        print("broker not configured")
        return
    store = Em6BybitStore()
    conn = store.open()
    rows = conn.execute(
        "SELECT id, symbol, opened_at, margin, pnl_usd FROM em6_bybit_trades "
        "WHERE status='closed' AND (pnl_usd IS NULL OR pnl_usd=0)"
    ).fetchall()
    updated = 0
    for row in rows:
        ex = broker.latest_closed_pnl(str(row["symbol"]), int(row["opened_at"]))
        if not ex or not ex.get("exit_price"):
            continue
        pnl = float(ex.get("pnl_usd") or 0)
        margin = float(row["margin"] or 1)
        roe = (pnl / margin * 100.0) if margin > 0 else 0.0
        conn.execute(
            "UPDATE em6_bybit_trades SET exit_price=?, pnl_usd=?, roe_pct=? WHERE id=?",
            (ex["exit_price"], pnl, roe, row["id"]),
        )
        updated += 1
    conn.commit()
    conn.close()
    print(f"updated {updated} of {len(rows)} closed rows")


if __name__ == "__main__":
    main()
