#!/usr/bin/env python3
"""Проверка 5 эталонных тикеров и текущего board_watches на сервере."""
from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from collector.rest_client import BybitRest
from signal_engine.pump_history import history_pump_metrics
from signal_engine.state import SymbolState
from signal_engine.swing_highs import find_two_peak_htf
from signal_engine.watch_store import WatchStore
from signal_engine.x2_retrace import (
    _eligible,
    _entry_quality_ok,
    _resolve_last_price,
    build_x2_retrace_board,
    price_change_7d_pct,
)

SYMS = ["NILUSDT", "HUMAUSDT", "MINAUSDT", "SANDUSDT", "GRASSUSDT"]


async def hydrate_symbol(rest: BybitRest, sym: str, turnover_map: dict[str, float], now: int) -> SymbolState:
    state = SymbolState(sym)
    for iv in ("240", "60", "D"):
        msg = await rest.fetch_klines(sym, iv)
        if msg and msg.get("data"):
            state.ingest(
                {"type": "kline", "symbol": sym, "timestamp": now, "data": msg["data"]}
            )
    turnover = turnover_map.get(sym)
    if turnover is not None:
        state.turnover_24h_usdt = turnover
    lp = _resolve_last_price(state)
    if lp is not None:
        state.last_price = lp
        state.ingest(
            {
                "type": "ticker",
                "symbol": sym,
                "timestamp": now,
                "data": {"turnover_24h": turnover or 0, "last_price": lp},
            }
        )
    return state


async def check_symbols() -> dict[str, SymbolState]:
    rest = BybitRest()
    await rest.open()
    now = int(time.time() * 1000)
    turnover_map = await rest.fetch_turnover_24h_by_symbol()
    states: dict[str, SymbolState] = {}
    print("=== REST + engine logic ===")
    for sym in SYMS:
        state = await hydrate_symbol(rest, sym, turnover_map, now)
        states[sym] = state
        hist = history_pump_metrics(state, now)
        if hist is None and state.bars_htf.get("240"):
            b4 = state.bars_htf["240"]
            lo, hi = min(b.low for b in b4), max(b.high for b in b4)
            print(f"  raw240 mult={hi/lo:.2f}" if lo else "")
        pump_start = hist.valley_ts if hist else 0
        b1 = state.bars_htf.get("60") or []
        b4 = state.bars_htf.get("240") or []
        tp = find_two_peak_htf(b1, b4, pump_start, now) if hist else None
        ok_el = _eligible(state)
        pct7 = price_change_7d_pct(state, now)
        quality = bool(
            hist and tp and ok_el and _entry_quality_ok(state, now, hist, tp, b1)
        )
        print(
            f"{sym}: mult={round(hist.peak_mult, 2) if hist else None} "
            f"peak={tp.kind if tp else None}@{tp.interval if tp else '-'} "
            f"7d={round(pct7, 2) if pct7 is not None else None}% "
            f"turnover={turnover_map.get(sym)} eligible={ok_el} enter={quality}"
        )
    await rest.close()
    return states


def check_db() -> set[str]:
    db = config.SQLITE_PATH
    print(f"\n=== board_watches ({db}) ===")
    if not db.is_file():
        print("DB missing")
        return set()
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT symbol, confirmed_stage FROM board_watches "
        "WHERE board='x2_retrace' AND dismissed=0 ORDER BY symbol"
    ).fetchall()
    active = {r[0] for r in rows}
    print("count:", len(active))
    for sym in SYMS:
        print(f"  {sym}: {'OK' if sym in active else 'MISSING'}")
    conn.close()
    return active


def simulate_board(states: dict[str, SymbolState]) -> set[str]:
    print("\n=== simulate build_x2_retrace_board (temp DB) ===")
    tmp = config.SQLITE_PATH.parent / "verify_x2_tmp.db"
    if tmp.is_file():
        tmp.unlink()
    store = WatchStore(tmp)
    store.open()
    now = int(time.time() * 1000)
    board = build_x2_retrace_board(states, now, store)
    on_board = set()
    for col in board.get("data", {}).get("columns") or []:
        for sig in col.get("signals") or []:
            on_board.add(sig["symbol"])
    for sym in SYMS:
        print(f"  {sym}: {'OK' if sym in on_board else 'MISSING'}")
    store.close()
    tmp.unlink()
    return on_board


def main() -> None:
    states = asyncio.run(check_symbols())
    check_db()
    simulate_board(states)


if __name__ == "__main__":
    main()
