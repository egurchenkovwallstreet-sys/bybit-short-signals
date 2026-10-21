#!/usr/bin/env python3
"""Сопоставить каждую закрытую em6_bybit сделку со своей записью closed PnL на Bybit."""
from __future__ import annotations

import sqlite3
from collections import defaultdict

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
        """
        SELECT id, symbol, opened_at, closed_at, entry_price, margin, pnl_usd
        FROM em6_bybit_trades WHERE status='closed' ORDER BY symbol, opened_at, id
        """
    ).fetchall()
    by_sym: dict[str, list] = defaultdict(list)
    for row in rows:
        by_sym[str(row["symbol"])].append(row)

    updated = 0
    for symbol, trades in by_sym.items():
        used: set[str] = set()
        for row in trades:
            ex = broker.match_closed_pnl(
                symbol,
                int(row["opened_at"]),
                float(row["entry_price"]),
                closed_at_ms=int(row["closed_at"]) if row["closed_at"] else None,
                used_keys=used,
            )
            if not ex or not ex.get("exit_price"):
                continue
            pnl = float(ex.get("pnl_usd") or 0)
            margin = float(row["margin"] or 1)
            roe = (pnl / margin * 100.0) if margin > 0 else 0.0
            closed_at = int(ex.get("closed_at_ms") or row["closed_at"] or 0)
            conn.execute(
                """
                UPDATE em6_bybit_trades
                SET exit_price=?, pnl_usd=?, roe_pct=?, closed_at=COALESCE(closed_at, ?)
                WHERE id=?
                """,
                (ex["exit_price"], pnl, roe, closed_at, row["id"]),
            )
            updated += 1
    conn.commit()
    pos = conn.execute(
        "SELECT COUNT(*) FROM em6_bybit_trades WHERE status='closed' AND pnl_usd>0"
    ).fetchone()[0]
    neg = conn.execute(
        "SELECT COUNT(*) FROM em6_bybit_trades WHERE status='closed' AND pnl_usd<0"
    ).fetchone()[0]
    conn.close()
    print(f"matched {updated} of {len(rows)} closed rows; pos={pos} neg={neg}")


if __name__ == "__main__":
    main()
