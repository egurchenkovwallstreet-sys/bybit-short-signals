"""Аудит и пересчёт закрытых paper-сделок после исправления стопов (1m / трейл / em6r).

Использование:
  py scripts/rebuild_paper_history.py audit
  py scripts/rebuild_paper_history.py apply --backup
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from signal_engine.paper.position import Position, long_roe_pct, roe_pct
from signal_engine.paper.strategy import _price_range
from signal_engine.paper.tape import minute_start
from signal_engine.paper.trade_side import resolve_trade_side
from signal_engine.state import Bar, SymbolState

CACHE_DIR = ROOT / "data" / "_kline_cache_rebuild"
FEE = config.PAPER_FEE_RATE_TAKER


def db_path() -> Path:
    for p in (Path("/opt/signals/data/paper_strategy.db"), ROOT / "data" / "paper_strategy.db"):
        if p.is_file():
            return p
    raise FileNotFoundError("paper_strategy.db not found")


def fetch_klines_1m(symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float, float, float, float]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{symbol}_1_{start_ms}_{end_ms}.json"
    if path.is_file():
        return [tuple(x) for x in json.loads(path.read_text(encoding="utf-8"))]

    out: list[tuple[int, float, float, float, float]] = []
    cursor = start_ms
    while cursor < end_ms:
        qs = urllib.parse.urlencode(
            {
                "category": "linear",
                "symbol": symbol,
                "interval": "1",
                "start": cursor,
                "end": end_ms,
                "limit": 1000,
            }
        )
        with urllib.request.urlopen(
            f"https://api.bybit.com/v5/market/kline?{qs}", timeout=45
        ) as resp:
            rows = json.loads(resp.read().decode()).get("result", {}).get("list") or []
        if not rows:
            break
        batch = []
        for r in rows:
            ts = int(r[0])
            if ts < start_ms or ts > end_ms:
                continue
            batch.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
        if not batch:
            break
        batch.sort(key=lambda x: x[0])
        out.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= cursor:
            break
        cursor = last_ts + 60_000
        time.sleep(0.05)
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


def gross_roe(entry: float, exit_p: float, side: str, lev: int) -> float:
    if side == "long":
        return long_roe_pct(entry, exit_p, lev)
    return roe_pct(entry, exit_p, lev)


def suspicious(row: sqlite3.Row) -> list[str]:
    flags: list[str] = []
    side = resolve_trade_side(side=row["side"], kind=row["kind"] or "", variant=row["variant"] or "")
    entry = float(row["entry_price"])
    exit_p = float(row["exit_price"] or 0)
    max_roe = float(row["max_roe"] or 0)
    roe = float(row["roe_pct"] or 0)
    best = float(row["best_price"] or entry)
    if entry <= 0 or exit_p <= 0:
        return flags
    g = gross_roe(entry, exit_p, side, int(row["leverage"]))
    if abs(g - roe) > 8 and row["exit_reason"] == "trailing_stop":
        flags.append("roe_vs_price_gap")
    if side == "long" and exit_p > best * 1.002 and roe > 0:
        flags.append("long_exit_above_best")
    if side == "short" and exit_p < best * 0.998 and roe > 0:
        flags.append("short_exit_below_best")
    if max_roe + 15 < roe and roe > 5:
        flags.append("exit_roe_above_max_roe")
    if max_roe > roe + 25 and roe < 0:
        flags.append("max_roe_vs_loss")
    return flags


def replay_trailing(row: sqlite3.Row) -> tuple[dict, Position] | None:
    if row["exit_reason"] not in ("trailing_stop", "liquidation"):
        return None
    side = resolve_trade_side(side=row["side"], kind=row["kind"] or "", variant=row["variant"] or "")
    variant = str(row["variant"] or "")
    opened = int(row["opened_at"])
    end = int(row["closed_at"] or opened) + 120_000
    klines = fetch_klines_1m(str(row["symbol"]), opened - 60_000, end)
    if not klines:
        return None

    pos = Position(
        symbol=str(row["symbol"]),
        opened_at=opened,
        entry_price=float(row["entry_price"]),
        margin=float(row["margin"]),
        leverage=int(row["leverage"]),
        side=side,
        stop_style=config.paper_stop_style(variant),
        paper_variant=variant,
    )
    pos.entry_fee = float(row["entry_fee"] or 0)
    pos.funding_paid = float(row["funding_paid"] or 0)

    state = SymbolState(str(row["symbol"]))
    last_check = opened
    for ts, o, h, l, c in klines:
        if ts + 60_000 <= opened:
            continue
        state.last_price = c
        state.bars_1m = [Bar(timestamp=ts, open=o, high=h, low=l, close=c, volume=0.0)]
        since = max(last_check, opened)
        low, high, last = _price_range(
            state, since, opened_at_ms=opened, entry_price=pos.entry_price
        )
        last_check = ts + 60_000
        reason = pos.update(low, high, last)
        if reason:
            override = pos.stop_price if reason == "trailing_stop" and variant == config.PAPER_EM6R_VARIANT else None
            return pos.close_result(reason, exit_price_override=override), pos
    return None


def rebuild_balances(conn: sqlite3.Connection) -> None:
    start = float(config.PAPER_START_BALANCE_USD)
    for variant in config.PAPER_VARIANTS:
        bal = start
        rows = conn.execute(
            """
            SELECT pnl_usd FROM paper_trades
            WHERE status = 'closed' AND variant = ? AND pnl_usd IS NOT NULL
            ORDER BY closed_at, id
            """,
            (variant,),
        )
        for (pnl,) in rows:
            bal += float(pnl or 0)
        conn.execute(
            "INSERT OR REPLACE INTO paper_kv(key, value) VALUES(?, ?)",
            (f"balance:{variant}", str(round(bal, 8))),
        )


def cmd_audit(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT * FROM paper_trades WHERE status = 'closed' ORDER BY closed_at"
    ).fetchall()
    by_flag: dict[str, int] = {}
    by_var: dict[str, int] = {}
    samples: list[tuple] = []
    for row in rows:
        flags = suspicious(row)
        if not flags:
            continue
        for f in flags:
            by_flag[f] = by_flag.get(f, 0) + 1
        v = str(row["variant"] or "?")
        by_var[v] = by_var.get(v, 0) + 1
        if len(samples) < 15:
            samples.append((row["id"], row["symbol"], v, flags, row["roe_pct"], row["max_roe"], row["exit_price"]))
    print(f"closed total: {len(rows)}")
    print(f"suspicious: {sum(1 for r in rows if suspicious(r))}")
    print("by flag:", dict(sorted(by_flag.items(), key=lambda x: -x[1])))
    print("by variant:", dict(sorted(by_var.items(), key=lambda x: -x[1])[:20]))
    for s in samples:
        print(" sample", s)


def cmd_apply(conn: sqlite3.Connection, limit: int | None) -> None:
    rows = conn.execute(
        "SELECT * FROM paper_trades WHERE status = 'closed' ORDER BY closed_at, id"
    ).fetchall()
    changed = 0
    for row in rows:
        if limit is not None and changed >= limit:
            break
        if not suspicious(row):
            continue
        if row["exit_reason"] not in ("trailing_stop", "liquidation"):
            continue
        replayed = replay_trailing(row)
        if replayed is None:
            continue
        new, pos = replayed
        old_pnl = float(row["pnl_usd"] or 0)
        new_pnl = float(new["pnl_usd"])
        if abs(old_pnl - new_pnl) < 0.02 and abs(float(row["exit_price"] or 0) - float(new["exit_price"])) < 1e-8:
            continue
        conn.execute(
            """
            UPDATE paper_trades SET
                exit_price = ?, exit_fee = ?, pnl_usd = ?, roe_pct = ?,
                max_roe = ?, min_roe = ?, best_price = ?, worst_price = ?,
                stop_price = ?
            WHERE id = ?
            """,
            (
                new["exit_price"],
                new["exit_fee"],
                new["pnl_usd"],
                new["roe_pct"],
                pos.max_roe(),
                pos.min_roe(),
                pos.best_price,
                pos.worst_price,
                pos.stop_price,
                row["id"],
            ),
        )
        changed += 1
        print(f"fixed id={row['id']} {row['symbol']} {row['variant']} pnl {old_pnl:.2f} -> {new_pnl:.2f}")
    rebuild_balances(conn)
    conn.commit()
    print(f"updated trades: {changed}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=("audit", "apply"))
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    path = db_path()
    if args.cmd == "apply" and args.backup:
        dest = path.with_suffix(f".pre_rebuild_{int(time.time())}.db")
        shutil.copy2(path, dest)
        print("backup", dest)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if args.cmd == "audit":
            cmd_audit(conn)
        else:
            cmd_apply(conn, args.limit)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
