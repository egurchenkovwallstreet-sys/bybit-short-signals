"""Аудит и полный пересчёт закрытых paper-сделок (1m / стоп / pivot-выход).

Использование:
  py scripts/rebuild_paper_history.py audit
  py scripts/rebuild_paper_history.py apply --backup --all
  py scripts/rebuild_paper_history.py report
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
from signal_engine.paper.trade_side import entry_from_raw, resolve_trade_side
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
        time.sleep(0.02)
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


def _entry_metrics(row: sqlite3.Row) -> dict:
    raw = row["entry_json"] if "entry_json" in row.keys() else None
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else {}
    except json.JSONDecodeError:
        return {}
    return dict(data.get("metrics") or {})


def position_from_row(row: sqlite3.Row) -> Position:
    variant = str(row["variant"] or "")
    side = resolve_trade_side(
        side=row["side"],
        kind=row["kind"] or "",
        variant=variant,
        entry=entry_from_raw(row["entry_json"] if "entry_json" in row.keys() else None),
    )
    entry = float(row["entry_price"])
    stop_row = float(row["stop_price"] or 0)
    metrics = _entry_metrics(row)
    desk = float(metrics.get("desk_initial_stop") or 0)
    if desk <= 0 and config.is_paper_333_family(variant) and stop_row > 0:
        desk = stop_row
    style = config.paper_stop_style(variant)
    init_stop = stop_row if stop_row > 0 else entry
    pos = Position(
        symbol=str(row["symbol"]),
        opened_at=int(row["opened_at"]),
        entry_price=entry,
        margin=float(row["margin"]),
        leverage=int(row["leverage"]),
        side=side,
        stop_style=style,
        paper_variant=variant,
        peak_gap_roe=config.paper_peak_gap_roe(variant),
        stop_price=init_stop,
        desk_initial_stop=desk if config.is_paper_333_family(variant) else 0.0,
    )
    pos.entry_fee = float(row["entry_fee"] or 0)
    pos.funding_paid = float(row["funding_paid"] or 0)
    if style == "bab" and stop_row > 0:
        pos.stop_price = stop_row
    return pos


def _walk_klines(
    row: sqlite3.Row,
    pos: Position,
    klines: list[tuple[int, float, float, float, float]],
    *,
    until_ms: int | None = None,
) -> str | None:
    opened = int(row["opened_at"])
    state = SymbolState(str(row["symbol"]))
    last_check = opened
    exit_reason: str | None = None
    for ts, o, h, l, c in klines:
        if until_ms is not None and ts > until_ms:
            break
        if ts + 60_000 <= opened:
            continue
        state.last_price = c
        state.bars_1m = [Bar(timestamp=ts, open=o, high=h, low=l, close=c, volume=0.0)]
        since = max(last_check, opened)
        low, high, last = _price_range(
            state, since, opened_at_ms=opened, entry_price=pos.entry_price
        )
        last_check = ts + 60_000
        exit_reason = pos.update(low, high, last)
        if exit_reason:
            break
    return exit_reason


def _close_pos(
    row: sqlite3.Row, pos: Position, reason: str, exit_override: float | None = None
) -> dict:
    variant = str(row["variant"] or "")
    override = exit_override
    if reason == "trailing_stop" and variant == config.PAPER_EM6R_VARIANT:
        override = pos.stop_price
    return pos.close_result(reason, exit_price_override=override)


def replay_stop_driven(row: sqlite3.Row) -> tuple[dict, Position] | None:
    if row["exit_reason"] not in ("trailing_stop", "liquidation"):
        return None
    opened = int(row["opened_at"])
    closed = int(row["closed_at"] or opened)
    end = max(closed + 120_000, opened + 60_000)
    klines = fetch_klines_1m(str(row["symbol"]), opened - 60_000, end)
    if not klines:
        return None
    pos = position_from_row(row)
    reason = _walk_klines(row, pos, klines)
    if not reason:
        stored = str(row["exit_reason"] or "trailing_stop")
        exit_p = float(row["exit_price"] or 0)
        if exit_p <= 0:
            return None
        return _close_pos(row, pos, stored, exit_p), pos
    return _close_pos(row, pos, reason), pos


def recalc_market_exit(row: sqlite3.Row) -> tuple[dict, Position] | None:
    """Pivot / manual: PnL по сохранённой цене; max_roe — по 1m до closed_at если есть klines."""
    exit_p = float(row["exit_price"] or 0)
    if exit_p <= 0:
        return None
    pos = position_from_row(row)
    reason = str(row["exit_reason"] or "manual")
    if reason not in ("opposite_pivot", "manual"):
        reason = "manual"
    opened = int(row["opened_at"])
    closed = int(row["closed_at"] or opened)
    klines = fetch_klines_1m(str(row["symbol"]), opened - 60_000, closed + 120_000)
    if klines:
        _walk_klines(row, pos, klines, until_ms=closed)
    return _close_pos(row, pos, reason, exit_p), pos


SKIP_REPLAY_REASONS = frozenset(
    {
        "слот занят",
        "вариант снят (баланс ≤ $1000)",
    }
)


def replay_trade(row: sqlite3.Row) -> tuple[dict, Position] | None:
    if row["exit_reason"] in ("trailing_stop", "liquidation"):
        return replay_stop_driven(row)
    return recalc_market_exit(row)


def rebuild_balances(conn: sqlite3.Connection) -> None:
    start = float(config.PAPER_START_BALANCE_USD)
    variants = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT variant FROM paper_trades WHERE variant IS NOT NULL AND variant != ''"
        )
    ]
    for variant in sorted(variants):
        bal = start
        rows = conn.execute(
            """
            SELECT id, pnl_usd FROM paper_trades
            WHERE status = 'closed' AND variant = ? AND pnl_usd IS NOT NULL
            ORDER BY closed_at, id
            """,
            (variant,),
        ).fetchall()
        for tid, pnl in rows:
            bb = bal
            bal += float(pnl or 0)
            conn.execute(
                "UPDATE paper_trades SET balance_before=?, balance_after=? WHERE id=?",
                (bb, bal, tid),
            )
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


def _apply_row(conn: sqlite3.Connection, row: sqlite3.Row, new: dict, pos: Position) -> bool:
    old_pnl = float(row["pnl_usd"] or 0)
    new_pnl = float(new["pnl_usd"])
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
    if abs(old_pnl - new_pnl) >= 0.02:
        print(
            f"  id={row['id']} {row['symbol']} {row['variant']} "
            f"pnl {old_pnl:.2f} -> {new_pnl:.2f} ({row['exit_reason']})"
        )
        return True
    return False


def cmd_apply(
    conn: sqlite3.Connection,
    limit: int | None,
    *,
    all_trades: bool,
) -> None:
    rows = conn.execute(
        "SELECT * FROM paper_trades WHERE status = 'closed' ORDER BY closed_at, id"
    ).fetchall()
    processed = 0
    pnl_changed = 0
    skipped = 0
    for row in rows:
        if limit is not None and processed >= limit:
            break
        if not all_trades and not suspicious(row):
            continue
        if str(row["exit_reason"] or "") in SKIP_REPLAY_REASONS:
            skipped += 1
            continue
        replayed = replay_trade(row)
        if replayed is None:
            skipped += 1
            continue
        new, pos = replayed
        if _apply_row(conn, row, new, pos):
            pnl_changed += 1
        processed += 1
        if processed % 200 == 0:
            print(f"... processed {processed}/{len(rows)}")
    rebuild_balances(conn)
    conn.commit()
    print(f"closed total: {len(rows)}")
    print(f"replayed: {processed}, pnl_changed: {pnl_changed}, skipped_no_klines: {skipped}")


def cmd_report(conn: sqlite3.Connection) -> None:
    start = float(config.PAPER_START_BALANCE_USD)
    rows = conn.execute(
        """
        SELECT variant,
               COUNT(*) AS n,
               SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) AS wins,
               ROUND(SUM(pnl_usd), 2) AS pnl,
               ROUND(AVG(roe_pct), 2) AS avg_roe
        FROM paper_trades
        WHERE status = 'closed' AND pnl_usd IS NOT NULL
        GROUP BY variant
        ORDER BY pnl DESC
        """
    ).fetchall()
    print(f"{'variant':<10} {'closed':>7} {'WR%':>7} {'sum_pnl':>12} {'balance':>12} {'kv':>12}")
    print("-" * 64)
    for r in rows:
        v = str(r["variant"])
        n = int(r["n"])
        wins = int(r["wins"] or 0)
        pnl = float(r["pnl"] or 0)
        wr = (100.0 * wins / n) if n else 0.0
        bal = start + pnl
        kv_row = conn.execute(
            "SELECT value FROM paper_kv WHERE key=?", (f"balance:{v}",)
        ).fetchone()
        kv = float(kv_row[0]) if kv_row else float("nan")
        print(f"{v:<10} {n:>7} {wr:>6.1f}% {pnl:>12.2f} {bal:>12.2f} {kv:>12.2f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=("audit", "apply", "report"))
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--all",
        action="store_true",
        help="пересчитать все закрытые сделки (не только suspicious)",
    )
    parser.add_argument(
        "--suspicious-only",
        action="store_true",
        help="только подозрительные + trailing/liquidation (старое поведение)",
    )
    args = parser.parse_args()
    all_trades = args.all or not args.suspicious_only
    if args.cmd == "apply" and not all_trades:
        all_trades = False
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
        elif args.cmd == "report":
            cmd_report(conn)
        else:
            cmd_apply(conn, args.limit, all_trades=all_trades)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
