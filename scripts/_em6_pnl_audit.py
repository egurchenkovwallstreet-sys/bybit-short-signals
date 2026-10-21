#!/usr/bin/env python3
"""Audit em6_bybit closed PnL vs Bybit API."""
from __future__ import annotations

import sqlite3

import config
from signal_engine.live.em6_bybit.broker import Em6BybitBroker


def main() -> None:
    conn = sqlite3.connect(config.PAPER_SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, symbol, opened_at, closed_at, entry_price, qty, pnl_usd, max_roe "
        "FROM em6_bybit_trades WHERE status='closed' ORDER BY id"
    ).fetchall()
    pos = sum(1 for r in rows if float(r["pnl_usd"] or 0) > 0)
    neg = sum(1 for r in rows if float(r["pnl_usd"] or 0) < 0)
    zero = sum(1 for r in rows if float(r["pnl_usd"] or 0) == 0)
    print("closed", len(rows), "pos", pos, "neg", neg, "zero", zero)
    print("sample last 8:")
    for r in rows[-8:]:
        print(dict(r))

    b = Em6BybitBroker()
    if b.configured() and rows:
        sym = rows[0]["symbol"]
        resp = b._client().get_closed_pnl(category="linear", symbol=sym, limit=50)
        api = (resp.get("result") or {}).get("list") or []
        print("bybit closed_pnl count", len(api), "for", sym)
        wins = sum(1 for x in api if float(x.get("closedPnl") or 0) > 0)
        losses = sum(1 for x in api if float(x.get("closedPnl") or 0) < 0)
        print("bybit wins", wins, "losses", losses)
        for x in api[:5]:
            print(
                " ",
                x.get("createdTime"),
                "pnl",
                x.get("closedPnl"),
                "entry",
                x.get("avgEntryPrice"),
                "exit",
                x.get("avgExitPrice"),
            )
    conn.close()


if __name__ == "__main__":
    main()
