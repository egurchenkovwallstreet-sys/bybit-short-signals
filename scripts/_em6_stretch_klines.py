#!/usr/bin/env python3
"""Отрыв EMA60 (5m) по REST klines Bybit — независимо от Redis."""
from __future__ import annotations

import config
from signal_engine.indicators import ema


def main() -> None:
    from pybit.unified_trading import HTTP

    http = HTTP(testnet=False, demo=True)
    tickers = (http.get_tickers(category="linear").get("result") or {}).get("list") or []
    by_turn = []
    for t in tickers:
        sym = t.get("symbol")
        if not sym or not str(sym).endswith("USDT"):
            continue
        turn = float(t.get("turnover24h") or 0)
        by_turn.append((turn, sym))
    by_turn.sort(reverse=True)
    floor = config.EM6_BYBIT_STRETCH_FLOOR_PCT
    hits: list[tuple[float, str, str]] = []
    for turn, sym in by_turn[:80]:
        resp = http.get_kline(category="linear", symbol=sym, interval="5", limit=200)
        rows = (resp.get("result") or {}).get("list") or []
        if len(rows) < 65:
            continue
        closes = [float(r[4]) for r in reversed(rows)]
        ema60 = ema(closes, 60)
        if ema60[-1] is None:
            continue
        e = float(ema60[-1])
        price = closes[-1]
        stretch = abs(price - e) / e * 100.0
        side = "long" if price < e else "short"
        if stretch + 1e-9 >= floor:
            hits.append((stretch, sym, side))
    hits.sort(reverse=True)
    print(f"top80 linear USDT by turnover; stretch >= {floor}%:", len(hits))
    for row in hits[:20]:
        print(f"  {row[1]} {row[2]} {row[0]:.2f}%")
    if not hits:
        best: list[tuple[float, str]] = []
        for turn, sym in by_turn[:30]:
            resp = http.get_kline(category="linear", symbol=sym, interval="5", limit=200)
            rows = (resp.get("result") or {}).get("list") or []
            if len(rows) < 65:
                continue
            closes = [float(r[4]) for r in reversed(rows)]
            ema60 = ema(closes, 60)
            if ema60[-1] is None:
                continue
            e = float(ema60[-1])
            price = closes[-1]
            stretch = abs(price - e) / e * 100.0
            best.append((stretch, sym))
        best.sort(reverse=True)
        print("max stretch top30:", best[:8])


if __name__ == "__main__":
    main()
