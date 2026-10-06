#!/usr/bin/env python3
"""Сверка turnover24h для активных x2 watches с Bybit."""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from collector.rest_client import BybitRest


async def main() -> None:
    db = config.SQLITE_PATH
    conn = sqlite3.connect(db)
    syms = [
        r[0]
        for r in conn.execute(
            "SELECT symbol FROM board_watches WHERE board='x2_retrace' AND dismissed=0"
        ).fetchall()
    ]
    conn.close()
    rest = BybitRest()
    await rest.open()
    turnover = await rest.fetch_turnover_24h_by_symbol()
    await rest.close()
    floor = config.X2_RETRACE_MIN_TURNOVER_24H_USDT
    bad = [(s, turnover.get(s, 0.0)) for s in syms if turnover.get(s, 0.0) < floor]
    print(f"watches={len(syms)} floor={floor}")
    print(f"below_floor={len(bad)}")
    for s, t in sorted(bad, key=lambda x: x[1])[:30]:
        print(f"  {s}: {t:.0f}")


if __name__ == "__main__":
    asyncio.run(main())
