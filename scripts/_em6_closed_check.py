#!/usr/bin/env python3
"""One-off: journal + Bybit closed PnL (run on VPS)."""
import sqlite3
import time

import config
from signal_engine.live.em6_bybit.broker import Em6BybitBroker

db = config.PAPER_SQLITE_PATH
conn = sqlite3.connect(str(db))
rows = conn.execute(
    "SELECT status, COUNT(1) FROM em6_bybit_trades GROUP BY status"
).fetchall()
print("db counts", rows)
closed = conn.execute(
    "SELECT symbol, side, pnl_usd, closed_at FROM em6_bybit_trades WHERE status='closed' ORDER BY closed_at DESC LIMIT 10"
).fetchall()
print("db closed sample", closed)
conn.close()

b = Em6BybitBroker()
if b.configured():
    start = int(time.time() * 1000) - 90 * 86400 * 1000
    ex = b.list_recent_closed_pnl(start_ms=start, limit=20, symbols=None)
    print("exchange closed count", len(ex))
    if ex:
        print("exchange sample", ex[:3])
else:
    print("broker not configured")
