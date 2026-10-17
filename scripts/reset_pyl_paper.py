#!/usr/bin/env python3
"""Сброс бумажного счёта БАБЛОСОС $$$ (pyl): сделки, equity, баланс $1000. Логику стратегии не трогает."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config

VARIANT = config.PAPER_PYL_VARIANT
START = config.PAPER_START_BALANCE_USD


def main() -> None:
    db_path = ROOT / "data" / "paper_strategy.db"
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])
    if not db_path.exists():
        print("no db:", db_path)
        sys.exit(1)
    con = sqlite3.connect(db_path)
    before = con.execute(
        "SELECT COUNT(1) FROM paper_trades WHERE variant = ? OR kind = ?",
        (VARIANT, VARIANT),
    ).fetchone()[0]
    con.execute("DELETE FROM paper_trades WHERE variant = ? OR kind = ?", (VARIANT, VARIANT))
    con.execute("DELETE FROM paper_equity_v WHERE variant = ?", (VARIANT,))
    con.execute(
        "INSERT INTO paper_kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (f"balance:{VARIANT}", str(START)),
    )
    con.commit()
    after = con.execute(
        "SELECT COUNT(1) FROM paper_trades WHERE variant = ? OR kind = ?",
        (VARIANT, VARIANT),
    ).fetchone()[0]
    bal = con.execute("SELECT value FROM paper_kv WHERE key = ?", (f"balance:{VARIANT}",)).fetchone()
    con.close()
    print(f"deleted {before} pyl trades, remaining {after}, balance={bal[0] if bal else '?'}")


if __name__ == "__main__":
    main()
