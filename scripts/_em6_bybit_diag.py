#!/usr/bin/env python3
"""Диагностика EMA6 Bybit: кошелёк, позиции, отрывы EMA60 ≥4%."""
from __future__ import annotations

import json
import time

import config
from signal_engine.live.em6_bybit.broker import Em6BybitBroker
from signal_engine.paper.ema60_stretch_detect import evaluate_ema60_stretch
from signal_engine.state import SymbolState

FLOOR = config.EM6_BYBIT_STRETCH_FLOOR_PCT
VARIANT = config.PAPER_EM6R_VARIANT


def ingest_redis(seconds: float = 14.0) -> dict[str, SymbolState]:
    import redis

    r = redis.Redis.from_url(config.REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    pubsub.subscribe(config.REDIS_CHANNEL_MARKET)
    states: dict[str, SymbolState] = {}
    deadline = time.time() + seconds
    while time.time() < deadline:
        msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if not msg or msg.get("type") != "message":
            continue
        raw = msg.get("data")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            continue
        sym = payload.get("symbol")
        if not sym:
            continue
        st = states.get(sym) or SymbolState(sym)
        states[sym] = st
        try:
            st.ingest(payload)
        except (TypeError, ValueError):
            pass
    pubsub.close()
    return states


def main() -> None:
    print("EM6_BYBIT_ENABLED", config.em6_bybit_enabled())
    b = Em6BybitBroker()
    print("broker configured", b.configured())
    if b.configured():
        w = b.wallet_usdt()
        print("wallet_usdt()", w)
        pos = b.linear_positions()
        print("open positions", len(pos))
        for p in pos:
            print(" ", p)
    states = ingest_redis()
    now_ms = int(time.time() * 1000)
    print("symbols from redis", len(states))
    min_turn = config.ema60_stretch_min_turnover_usdt(VARIANT)
    print("turnover min (em6r variant)", min_turn)
    ge4: list[tuple[float, str, str, str]] = []
    ge4_turn: list[tuple[float, str, str]] = []
    top_stretch: list[tuple[float, str]] = []
    for sym, st in states.items():
        if not st.last_price:
            continue
        ev = evaluate_ema60_stretch(st, now_ms)
        stretch = float(ev.metrics.get("stretch_pct") or 0)
        top_stretch.append((stretch, sym))
        if stretch + 1e-9 >= FLOOR and ev.side in ("long", "short"):
            ge4.append((stretch, sym, ev.side, "pass" if ev.passed else "fail_ev"))
            turn = st.turnover_24h_usdt
            if turn is not None and float(turn) >= float(min_turn or 0):
                ge4_turn.append((stretch, sym, ev.side))
    top_stretch.sort(reverse=True)
    ge4.sort(reverse=True)
    ge4_turn.sort(reverse=True)
    print(f"stretch >= {FLOOR}% (any side):", len(ge4))
    for row in ge4[:15]:
        print(" ", row)
    print(f"stretch >= {FLOOR}% + turnover:", len(ge4_turn))
    for row in ge4_turn[:15]:
        print(" ", row)
    print("top 10 stretch (all symbols):")
    for st, sym in top_stretch[:10]:
        print(f"  {sym} {st:.2f}%")


if __name__ == "__main__":
    main()
