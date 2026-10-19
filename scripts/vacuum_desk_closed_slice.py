"""Срез закрытых сделок desk-стратегий Пылесос (pyl, pyl1, 333, vps5, vps15)."""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from signal_engine.paper.analytics import list_trades

DESK = ("pyl", "333", "vps15")
# Как во вкладке «Пылесос LH» (vacuum_lh.js)
DESK_LABEL = {
    "pyl": "БАБЛОСОС",
    "pyl1": "БАБЛОСОС 1",
    "333": "333",
    "vps5": "Пылесос 5",
    "vps15": "Пылесос 15",
}


def vlabel(variant: str) -> str:
    return DESK_LABEL.get(variant, variant)
EXIT_RU = {
    "opposite_pivot": "противоп. pivot",
    "stop": "стоп",
    "trailing_stop": "трейл",
    "liquidation": "ликвидация",
    "manual": "вручную",
}


def side_label(row: dict) -> str:
    s = row.get("side")
    if s:
        return str(s)
    entry = row.get("entry") or {}
    m = entry.get("metrics") or {}
    return str(m.get("side") or entry.get("side") or "?")


def pivot_kind(row: dict) -> str:
    m = (row.get("entry") or {}).get("metrics") or {}
    return str(m.get("pivot_kind") or "?")


def left_strength(row: dict) -> int | None:
    m = (row.get("entry") or {}).get("metrics") or {}
    v = m.get("left_strength")
    return int(v) if v is not None else None


def chop_at_entry(row: dict) -> dict | None:
    m = (row.get("entry") or {}).get("metrics") or {}
    c = m.get("chop")
    return c if isinstance(c, dict) else None


def hour_range(row: dict) -> float | None:
    m = (row.get("entry") or {}).get("metrics") or {}
    v = m.get("hour_range_pct")
    return float(v) if v is not None else None


def market_bias_short(row: dict) -> str:
    """Грубая оценка «направление при входе» по side сделки + pivot."""
    side = side_label(row)
    pk = pivot_kind(row)
    if side == "short" and pk in ("LH", "high", "peak"):
        return "шорт по LH (откат от вершины)"
    if side == "long" and pk in ("HL", "low", "trough"):
        return "лонг по HL (отскок от дна)"
    return f"{side} / pivot {pk}"


def summarize_group(rows: list[dict], label: str) -> None:
    if not rows:
        print(f"  {label}: 0 сделок")
        return
    pnls = [float(r.get("pnl_usd") or 0) for r in rows]
    roes = [float(r.get("roe_pct") or 0) for r in rows if r.get("roe_pct") is not None]
    mfe = [float(r.get("max_roe") or 0) for r in rows]
    mae = [float(r.get("min_roe") or 0) for r in rows]
    dur_min = [
        (float(r["closed_at"]) - float(r["opened_at"])) / 60_000
        for r in rows
        if r.get("closed_at") and r.get("opened_at")
    ]
    print(f"  {label}: n={len(rows)}  net=${sum(pnls):.2f}  avg_pnl=${statistics.mean(pnls):.2f}")
    if roes:
        print(f"    ROE avg={statistics.mean(roes):+.1f}%  med={statistics.median(roes):+.1f}%")
    if mfe:
        print(f"    max_roe (MFE) avg={statistics.mean(mfe):+.1f}%  min_roe (MAE) avg={statistics.mean(mae):+.1f}%")
    if dur_min:
        print(f"    время в сделке: med={statistics.median(dur_min):.0f} мин")

    exits = Counter(str(r.get("exit_reason") or "?") for r in rows)
    print(f"    выходы: {', '.join(f'{EXIT_RU.get(k,k)}={v}' for k,v in exits.most_common())}")

    sides = Counter(side_label(r) for r in rows)
    print(f"    стороны: {dict(sides)}")

    biases = Counter(market_bias_short(r) for r in rows)
    top_bias = biases.most_common(3)
    print(f"    контекст входа (топ): {top_bias}")

    ls = [left_strength(r) for r in rows if left_strength(r) is not None]
    if ls:
        print(f"    left_strength: avg={statistics.mean(ls):.1f}  med={statistics.median(ls):.0f}")

    hr = [hour_range(r) for r in rows if hour_range(r) is not None]
    if hr:
        print(f"    hour_range% (pyl1): avg={statistics.mean(hr):.2f}%  n={len(hr)}")

    chops = [chop_at_entry(r) for r in rows if chop_at_entry(r)]
    if chops:
        tight = sum(1 for c in chops if c.get("tight"))
        rp = [c["range_pct"] for c in chops if c.get("range_pct") is not None]
        print(f"    chop (333): tight={tight}/{len(chops)}  range% avg={statistics.mean(rp):.2f}" if rp else f"    chop: n={len(chops)}")


def compare_win_loss(wins: list[dict], losses: list[dict]) -> None:
    def avg(key_fn, rows):
        vals = [x for x in (key_fn(r) for r in rows) if x is not None]
        return statistics.mean(vals) if vals else None

    print("  --- win vs loss (средние) ---")
    for name, fn in (
        ("max_roe", lambda r: float(r.get("max_roe") or 0)),
        ("min_roe", lambda r: float(r.get("min_roe") or 0)),
        ("|roe|", lambda r: abs(float(r.get("roe_pct") or 0))),
        ("left_L", left_strength),
        ("hour_range%", hour_range),
    ):
        w = avg(fn, wins)
        l = avg(fn, losses)
        if w is not None and l is not None:
            print(f"    {name}: win={w:.2f}  loss={l:.2f}  Δ={w-l:+.2f}")


def main() -> None:
    conn = sqlite3.connect(config.PAPER_SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    all_rows: dict[str, list[dict]] = {}
    for v in DESK:
        all_rows[v] = [t for t in list_trades(conn, "closed", 5000, variant=v)]

    print("=== ПЫЛЕСОС DESK: закрытые сделки ===\n")
    grand_w, grand_l = [], []
    for variant in DESK:
        rows = all_rows[variant]
        wins = [r for r in rows if float(r.get("pnl_usd") or 0) > 0]
        losses = [r for r in rows if float(r.get("pnl_usd") or 0) <= 0]
        grand_w.extend(wins)
        grand_l.extend(losses)
        print(f"## {vlabel(variant)}  (всего {len(rows)}, +{len(wins)} / -{len(losses)})")
        if not rows:
            print()
            continue
        wr = 100 * len(wins) / len(rows)
        print(f"  WR={wr:.1f}%  net=${sum(float(r.get('pnl_usd') or 0) for r in rows):.2f}")
        summarize_group(wins, "ПЛЮС")
        summarize_group(losses, "МИНУС")
        compare_win_loss(wins, losses)
        print()

    print("=== ВСЕ DESK вместе ===")
    print(f"  n={len(grand_w)+len(grand_l)}  +{len(grand_w)} -{len(grand_l)}")
    summarize_group(grand_w, "ПЛЮС все")
    summarize_group(grand_l, "МИНУС все")
    compare_win_loss(grand_w, grand_l)

    print("\n=== Общие паттерны (все desk) ===")
    loss_exits = Counter(str(r.get("exit_reason")) for r in grand_l)
    win_exits = Counter(str(r.get("exit_reason")) for r in grand_w)
    print(f"  Минусы чаще выходят: {loss_exits.most_common(5)}")
    print(f"  Плюсы чаще выходят: {win_exits.most_common(5)}")
    loss_mfe = statistics.mean([float(r.get("max_roe") or 0) for r in grand_l]) if grand_l else 0
    win_mfe = statistics.mean([float(r.get("max_roe") or 0) for r in grand_w]) if grand_w else 0
    print(f"  Средний max_roe: плюсы {win_mfe:+.1f}% vs минусы {loss_mfe:+.1f}% — у минусов часто был шанс (MFE), но отдали.")

    print("\n=== По стороне (long / short) ===")
    for variant in DESK:
        rows = all_rows[variant]
        if not rows:
            continue
        print(f"  {vlabel(variant)}:")
        for side in ("long", "short"):
            sub = [r for r in rows if side_label(r) == side]
            if not sub:
                continue
            w = sum(1 for r in sub if float(r.get("pnl_usd") or 0) > 0)
            print(
                f"    {side}: n={len(sub)} WR={100 * w / len(sub):.1f}% "
                f"net=${sum(float(r.get('pnl_usd') or 0) for r in sub):.0f}"
            )

    print("\n=== Убытки: never green (max_roe < 1%) vs отдача (max_roe ≥ 3%, pnl ≤ 0) ===")
    for variant in DESK:
        rows = all_rows[variant]
        losses = [r for r in rows if float(r.get("pnl_usd") or 0) <= 0]
        if not losses:
            continue
        ng = [r for r in losses if float(r.get("max_roe") or 0) < 1]
        gb = [r for r in losses if float(r.get("max_roe") or 0) >= 3]
        print(
            f"  {vlabel(variant)}: сразу против нас {len(ng)}/{len(losses)} ({100 * len(ng) / len(losses):.0f}%), "
            f"отдали после +3% {len(gb)}/{len(losses)} ({100 * len(gb) / len(losses):.0f}%)"
        )

    print("\n=== БАБЛОСОС 1: structure_bias (win vs loss) ===")
    rows = all_rows["pyl1"]
    for label, subset in (("win", [r for r in rows if float(r.get("pnl_usd") or 0) > 0]), ("loss", [r for r in rows if float(r.get("pnl_usd") or 0) <= 0])):
        c = Counter((r.get("entry") or {}).get("metrics", {}).get("structure_bias") or "?" for r in subset)
        print(f"  {label}: {dict(c.most_common())}")

    print("\n=== Пылесос 5 / Пылесос 15: pivot vs trail на плюсах и минусах ===")
    for variant in ("vps5", "vps15"):
        rows = all_rows[variant]
        for wl, name in (([r for r in rows if float(r.get("pnl_usd") or 0) > 0], "+"), ([r for r in rows if float(r.get("pnl_usd") or 0) <= 0], "-")):
            c = Counter(str(r.get("exit_reason")) for r in wl)
            print(f"  {vlabel(variant)} {name}: {dict(c)}")


if __name__ == "__main__":
    main()
