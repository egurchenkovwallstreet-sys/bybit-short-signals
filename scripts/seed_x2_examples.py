#!/usr/bin/env python3
"""Один раз подтянуть эталонные тикеры в board_watches через REST (если проходят правила)."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from collector.rest_client import BybitRest
from scripts.verify_x2_examples import SYMS, hydrate_symbol
from signal_engine.watch_store import WatchStore
from signal_engine.x2_retrace import build_x2_retrace_board


async def main() -> None:
    rest = BybitRest()
    await rest.open()
    now = int(time.time() * 1000)
    turnover_map = await rest.fetch_turnover_24h_by_symbol()
    states = {}
    for sym in SYMS:
        states[sym] = await hydrate_symbol(rest, sym, turnover_map, now)
    await rest.close()

    store = WatchStore(config.SQLITE_PATH)
    store.open()
    build_x2_retrace_board(states, now, store)
    store.close()
    print("seeded", SYMS, "into", config.SQLITE_PATH)


if __name__ == "__main__":
    asyncio.run(main())
