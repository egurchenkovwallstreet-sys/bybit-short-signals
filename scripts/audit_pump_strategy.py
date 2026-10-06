#!/usr/bin/env python3
"""Сколько пар проходит фильтр «Поиск пампов» по кэшу движка (REST Bybit)."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from collector.rest_client import BybitRest
from signal_engine.pump_strategy import detect_best_pump, detect_long_pump, detect_short_pump
from signal_engine.state import Bar, SymbolState


def _bars_from_candles(candles: list[dict], interval: str) -> list[Bar]:
    out: list[Bar] = []
    for row in candles:
        ts = int(row.get("timestamp") or 0)
        o = float(row["open"])
        h = float(row["high"])
        lo = float(row["low"])
        c = float(row["close"])
        v = float(row.get("volume") or 0)
        out.append(Bar(ts, o, h, lo, c, v, from_kline=True))
    return out


async def main() -> None:
    rest = BybitRest()
    await rest.open()
    now_ms = int(time.time() * 1000)
    turnover = await rest.fetch_turnover_24h_by_symbol()
    symbols = [
        s
        for s, t in turnover.items()
        if t >= config.PUMP_STRATEGY_MIN_TURNOVER_24H_USDT
    ]
    symbols.sort(key=lambda s: turnover[s], reverse=True)
    print(f"С оборотом ≥{config.PUMP_STRATEGY_MIN_TURNOVER_24H_USDT:.0f}: {len(symbols)}")

    long_hits: list[str] = []
    short_hits: list[str] = []
    limit = min(len(symbols), 120)
    for symbol in symbols[:limit]:
        state = SymbolState(symbol)
        state.turnover_24h_usdt = turnover[symbol]
        for interval in ("D", "240", "60", "5", "15"):
            msg = await rest.fetch_klines(symbol, interval)
            if not msg:
                continue
            candles = (msg.get("data") or {}).get("candles") or []
            if interval in ("5", "15"):
                state.bars_htf[interval] = _bars_from_candles(candles, interval)
            elif interval == "1":
                state.bars_1m = _bars_from_candles(candles, interval)
            else:
                state.bars_htf[interval] = _bars_from_candles(candles, interval)
        oi_msg = await rest.fetch_open_interest(symbol, "5min")
        if oi_msg:
            state.ingest(oi_msg)
        if detect_short_pump(state, now_ms):
            short_hits.append(symbol)
        if detect_long_pump(state, now_ms):
            long_hits.append(symbol)

    print(f"Проверено (топ по обороту): {limit}")
    print(f"Быстрый памп: {len(short_hits)}")
    print(f"Длинный рост: {len(long_hits)}")
    if long_hits[:15]:
        print("Длинный (примеры):", ", ".join(long_hits[:15]))
    await rest.close()


if __name__ == "__main__":
    asyncio.run(main())
