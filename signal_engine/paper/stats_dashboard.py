"""Сводка для вкладки «Статистика»: бумажные варианты, шорт/лонг, дни и недели (МСК)."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import config
from signal_engine.paper.analytics import MSK, _equity, _loads, _pnl_pack, _trade_stats, msk_day_start_ms
from signal_engine.paper.detect import VARIANT_LABELS
from signal_engine.paper.trade_side import resolve_trade_side


def _side_for_row(row: sqlite3.Row) -> str:
    return resolve_trade_side(
        side=row["side"] if "side" in row.keys() else None,
        kind=str(row["kind"] or "") if "kind" in row.keys() else "",
        variant=str(row["variant"] or ""),
        entry=_loads(row["entry_json"] if "entry_json" in row.keys() else None),
    )


def _side_summary(rows: list[sqlite3.Row]) -> dict[str, Any]:
    start = float(config.PAPER_START_BALANCE_USD)
    shorts = [r for r in rows if _side_for_row(r) == "short"]
    longs = [r for r in rows if _side_for_row(r) == "long"]
    return {
        "short": _pnl_pack([float(r["pnl_usd"] or 0) for r in shorts], start),
        "long": _pnl_pack([float(r["pnl_usd"] or 0) for r in longs], start),
    }


def _period_slice(rows: list[sqlite3.Row], start_ms: int, end_ms: int) -> dict[str, Any]:
    start = float(config.PAPER_START_BALANCE_USD)
    bucket = [r for r in rows if r["closed_at"] and start_ms <= int(r["closed_at"]) < end_ms]
    pnls = [float(r["pnl_usd"] or 0) for r in bucket]
    sides = _side_summary(bucket)
    return {
        "all": _pnl_pack(pnls, start),
        "short": sides["short"],
        "long": sides["long"],
    }


def last_msk_days(now_ms: int, n: int = 10) -> list[dict[str, Any]]:
    dt = datetime.fromtimestamp(now_ms / 1000.0, tz=MSK)
    today = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    out: list[dict[str, Any]] = []
    for offset in range(n - 1, -1, -1):
        day_start = today - timedelta(days=offset)
        day_end = day_start + timedelta(days=1)
        out.append(
            {
                "label": day_start.strftime("%d.%m"),
                "weekday": day_start.strftime("%a"),
                "from_ms": int(day_start.timestamp() * 1000),
                "to_ms": int(day_end.timestamp() * 1000),
            }
        )
    return out


def last_msk_weeks(now_ms: int, n: int = 8) -> list[dict[str, Any]]:
    """8 скользящих 7-суточных интервалов, последний заканчивается в полночь следующего дня после «сегодня»."""
    dt = datetime.fromtimestamp(now_ms / 1000.0, tz=MSK)
    today = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    horizon_end = today + timedelta(days=1)
    out: list[dict[str, Any]] = []
    for index in range(n):
        end = horizon_end - timedelta(days=7 * index)
        start = end - timedelta(days=7)
        label_end = end - timedelta(seconds=1)
        out.append(
            {
                "label": f"{start.strftime('%d.%m')}–{label_end.strftime('%d.%m')}",
                "from_ms": int(start.timestamp() * 1000),
                "to_ms": int(end.timestamp() * 1000),
            }
        )
    out.reverse()
    return out


def _metrics_from_rows(rows: list[sqlite3.Row]) -> dict[str, Any]:
    raw = _trade_stats(rows)
    pf = raw.get("profit_factor")
    if pf == "∞":
        pf_gauge = 3.0
    elif pf is None:
        pf_gauge = 0.0
    else:
        pf_gauge = float(pf)
    return {
        **raw,
        "profit_factor_gauge": round(min(pf_gauge, 3.0), 2),
        "avg_trade": round(raw["total_pnl"] / raw["closed"], 2) if raw["closed"] else 0.0,
    }


def _global_equity(rows: list[sqlite3.Row]) -> list[float]:
    ordered = sorted(rows, key=lambda r: int(r["closed_at"] or 0))
    start = float(config.PAPER_START_BALANCE_USD)
    curve = [round(start, 2)]
    running = start
    for row in ordered:
        running += float(row["pnl_usd"] or 0)
        curve.append(round(running, 2))
    return curve


def compute_paper_stats_dashboard(path: Path | str, now_ms: int | None = None) -> dict[str, Any]:
    database = Path(path)
    if not database.is_file():
        return empty_paper_stats_dashboard()
    now_ms = int(now_ms or time.time() * 1000)
    try:
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return empty_paper_stats_dashboard()
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'paper_trades'"
        ).fetchone()
        if table is None:
            return empty_paper_stats_dashboard()
        all_closed = list(
            conn.execute(
                "SELECT * FROM paper_trades WHERE status = 'closed' ORDER BY closed_at"
            )
        )
        by_variant: dict[str, list[sqlite3.Row]] = {v: [] for v in config.PAPER_VARIANTS}
        for row in all_closed:
            variant = str(row["variant"] or "")
            if variant not in by_variant:
                by_variant[variant] = []
            by_variant[variant].append(row)

        day_defs = last_msk_days(now_ms, 10)
        week_defs = last_msk_weeks(now_ms, 8)
        variants_out: list[dict[str, Any]] = []
        for variant in config.PAPER_VARIANTS:
            rows = by_variant.get(variant) or []
            metrics = _metrics_from_rows(rows)
            sides = _side_summary(rows)
            variants_out.append(
                {
                    "id": variant,
                    "label": VARIANT_LABELS.get(variant, variant),
                    "metrics": metrics,
                    "sides": sides,
                    "days": [
                        {**d, "stats": _period_slice(rows, d["from_ms"], d["to_ms"])} for d in day_defs
                    ],
                    "weeks": [
                        {**w, "stats": _period_slice(rows, w["from_ms"], w["to_ms"])} for w in week_defs
                    ],
                    "equity": _equity(conn, variant) if rows else [],
                }
            )
        global_metrics = _metrics_from_rows(all_closed)
        return {
            "paper": True,
            "demo": False,
            "as_of": datetime.fromtimestamp(now_ms / 1000.0, tz=MSK).strftime("%d.%m.%Y %H:%M МСК"),
            "day_start_ms": msk_day_start_ms(now_ms),
            "global": {
                "metrics": global_metrics,
                "sides": _side_summary(all_closed),
                "equity": _global_equity(all_closed),
            },
            "variants": variants_out,
        }
    finally:
        conn.close()


def empty_paper_stats_dashboard() -> dict[str, Any]:
    empty_metrics = _metrics_from_rows([])
    empty_side = _pnl_pack([], float(config.PAPER_START_BALANCE_USD))
    variants = [
        {
            "id": variant,
            "label": VARIANT_LABELS.get(variant, variant),
            "metrics": empty_metrics,
            "sides": {"short": empty_side, "long": empty_side},
            "days": [],
            "weeks": [],
            "equity": [],
        }
        for variant in config.PAPER_VARIANTS
    ]
    return {
        "paper": True,
        "demo": False,
        "as_of": "",
        "day_start_ms": 0,
        "global": {
            "metrics": empty_metrics,
            "sides": {"short": empty_side, "long": empty_side},
            "equity": [float(config.PAPER_START_BALANCE_USD)],
        },
        "variants": variants,
    }
