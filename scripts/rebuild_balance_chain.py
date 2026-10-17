#!/usr/bin/env python3
"""Пересчитать balance_before/after по closed_at для variant (история параллельных сделок)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config

variant = sys.argv[1] if len(sys.argv) > 1 else config.PAPER_VPS15_VARIANT
db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "paper_strategy.db"

con = sqlite3.connect(db_path)
rows = con.execute(
    "SELECT id, pnl_usd FROM paper_trades WHERE variant=? AND status='closed' ORDER BY closed_at, id",
    (variant,),
).fetchall()
bal = float(config.PAPER_START_BALANCE_USD)
for tid, pnl in rows:
    pnl = float(pnl or 0)
    bb = bal
    ba = bal + pnl
    con.execute(
        "UPDATE paper_trades SET balance_before=?, balance_after=? WHERE id=?",
        (bb, ba, tid),
    )
    bal = ba
con.execute(
    "INSERT INTO paper_kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
    (f"balance:{variant}", str(bal)),
)
con.commit()
print(f"{variant}: rebuilt {len(rows)} closes, balance_kv={bal:.4f}")
