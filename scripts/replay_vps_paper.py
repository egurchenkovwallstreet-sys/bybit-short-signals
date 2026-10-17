#!/usr/bin/env python3
"""Пересчёт paper vps15/vps5 по правилам стопа. Перед --apply остановить signal-engine."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from signal_engine.paper.vps_replay import apply_replay_to_db, replay_variant_trades


def fetch_klines_1m(symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float, float, float, float]]:
    out: list[tuple[int, float, float, float, float]] = []
    cursor = start_ms
    while cursor < end_ms:
        qs = urllib.parse.urlencode(
            {"category": "linear", "symbol": symbol, "interval": "1", "start": cursor, "limit": 1000}
        )
        url = f"https://api.bybit.com/v5/market/kline?{qs}"
        with urllib.request.urlopen(url, timeout=45) as resp:
            data = json.loads(resp.read().decode())
        rows = data.get("result", {}).get("list") or []
        if not rows:
            break
        batch = []
        for row in rows:
            ts = int(row[0])
            if start_ms <= ts <= end_ms:
                batch.append((ts, float(row[1]), float(row[2]), float(row[3]), float(row[4])))
        if not batch:
            break
        batch.sort(key=lambda x: x[0])
        out.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= cursor:
            break
        cursor = last_ts + 60_000
        time.sleep(0.05)
        if len(rows) < 1000:
            break
    by_ts = {t[0]: t for t in out}
    return sorted(by_ts.values(), key=lambda x: x[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(config.PAPER_SQLITE_PATH))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--variant", action="append", dest="variants")
    args = parser.parse_args()
    variants = args.variants or list(config.PAPER_VPS_VARIANTS)
    now_ms = int(time.time() * 1000)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    summaries = []
    for variant in variants:
        rows = list(
            conn.execute(
                "SELECT * FROM paper_trades WHERE variant=? ORDER BY opened_at, id",
                (variant,),
            )
        )
        if not rows:
            print(variant, "нет сделок")
            continue
        start = min(int(r["opened_at"]) for r in rows) - 60_000
        symbols = sorted({str(r["symbol"]) for r in rows})
        bars_by_symbol = {}
        for symbol in symbols:
            bars_by_symbol[symbol] = fetch_klines_1m(symbol, start, now_ms)
            print(variant, symbol, "свечей", len(bars_by_symbol[symbol]))
        results = replay_variant_trades(rows, bars_by_symbol, now_ms)
        open_n = sum(1 for r in results if r.status == "open")
        closed_n = sum(1 for r in results if r.status == "closed")
        skipped = sum(1 for r in results if r.skipped)
        liq = sum(1 for r in results if r.reason == "liquidation")
        pnl = sum(r.pnl_usd for r in results if r.status == "closed")
        print(
            variant,
            "сделок",
            len(results),
            "открытых",
            open_n,
            "закрытых",
            closed_n,
            "слот занят",
            skipped,
            "ликвидаций",
            liq,
            "сумма pnl",
            round(pnl, 2),
            "баланс",
            round(config.PAPER_START_BALANCE_USD + pnl, 2),
        )
        for item in results:
            mark = "SKIP" if item.skipped else item.status
            print(
                f"  {item.trade_id} {item.symbol} {item.side} {mark} "
                f"reason={item.reason or '-'} pnl={item.pnl_usd:.2f} roe={item.roe_pct:.1f}"
            )
        if args.apply:
            summary = apply_replay_to_db(conn, variant, results, now_ms)
            summaries.append(summary)
            print("записано", summary)
        else:
            print("сухой прогон, база не менялась")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
