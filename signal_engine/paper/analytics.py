"""Статистика теста стратегии по SQLite: сделки и кандидаты без входа."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import config

EXIT_LABELS = {"trailing_stop": "Трейлинг-стоп", "liquidation": "Ликвидация"}


def compute_analytics(conn: sqlite3.Connection, balance: float | None = None) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    closed = list(conn.execute("SELECT * FROM paper_trades WHERE status = 'closed' ORDER BY closed_at"))
    open_count = conn.execute("SELECT COUNT(*) FROM paper_trades WHERE status = 'open'").fetchone()[0]
    trades = _trade_stats(closed)
    trades["open"] = int(open_count)
    if balance is not None:
        trades["balance"] = round(balance, 2)
    return {
        "trades": trades,
        "by_reason": _group(closed, lambda r: EXIT_LABELS.get(r["exit_reason"], r["exit_reason"] or "—")),
        "by_kind": _group(closed, lambda r: "Короткий памп" if r["kind"] == "short" else "Длинный памп"),
        "by_grade": _group(closed, lambda r: f"Сила {r['grade'] or 'C'}"),
        "by_btc": _group(closed, lambda r: "BTC строгий режим" if r["strict_btc"] else "BTC обычный"),
        "by_trigger": _group(closed, _trigger_label),
        "equity": _equity(conn),
        "candidates": _candidate_stats(conn),
    }


def _trade_stats(rows: list[sqlite3.Row]) -> dict[str, Any]:
    pnls = [float(r["pnl_usd"] or 0) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    start = config.PAPER_START_BALANCE_USD
    peak = start
    max_dd = 0.0
    running = start
    for p in pnls:
        running += p
        peak = max(peak, running)
        if peak > 0:
            max_dd = max(max_dd, (peak - running) / peak * 100.0)
    durations = [
        (int(r["closed_at"]) - int(r["opened_at"])) / 60_000 for r in rows if r["closed_at"] and r["opened_at"]
    ]
    fees = sum(float(r["entry_fee"] or 0) + float(r["exit_fee"] or 0) for r in rows)
    funding = sum(float(r["funding_paid"] or 0) for r in rows)
    roes = [float(r["roe_pct"] or 0) for r in rows]
    return {
        "closed": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(rows) * 100.0, 1) if rows else 0.0,
        "total_pnl": round(sum(pnls), 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else (None if not wins else "∞"),
        "max_drawdown_pct": round(max_dd, 2),
        "best": round(max(pnls), 2) if pnls else 0.0,
        "worst": round(min(pnls), 2) if pnls else 0.0,
        "avg_roe": round(sum(roes) / len(roes), 1) if roes else 0.0,
        "avg_duration_min": round(sum(durations) / len(durations)) if durations else 0,
        "fees": round(fees, 2),
        "funding": round(funding, 2),
        "liquidations": sum(1 for r in rows if r["exit_reason"] == "liquidation"),
        "trailing_wins": sum(1 for r in rows if r["exit_reason"] == "trailing_stop" and float(r["pnl_usd"] or 0) > 0),
    }


def _group(rows: list[sqlite3.Row], key) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    for row in rows:
        buckets.setdefault(str(key(row)), []).append(float(row["pnl_usd"] or 0))
    out = []
    for label, pnls in sorted(buckets.items()):
        wins = sum(1 for p in pnls if p > 0)
        out.append(
            {
                "label": label,
                "count": len(pnls),
                "wins": wins,
                "win_rate": round(wins / len(pnls) * 100.0, 1),
                "pnl": round(sum(pnls), 2),
            }
        )
    return out


def _trigger_label(row: sqlite3.Row) -> str:
    entry = _loads(row["entry_json"])
    trigger = ((entry.get("metrics") or {}).get("pump") or {}).get("trigger") or "?"
    return {"4h": "Рост за ≤4 ч", "24h": "Рост за 24 ч", "7d": "Рост за 7 д", "14d": "Рост за 14 д"}.get(trigger, trigger)


def _equity(conn: sqlite3.Connection) -> list[list[float]]:
    rows = conn.execute("SELECT ts, balance, equity FROM paper_equity ORDER BY ts DESC LIMIT 2000").fetchall()
    return [[int(r["ts"]), round(float(r["balance"]), 2), round(float(r["equity"]), 2)] for r in reversed(rows)]


def _candidate_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = list(conn.execute("SELECT * FROM paper_candidates"))
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1

    # Что держало кандидата без входа: последний срез перед окончанием.
    blockers: dict[str, int] = {}
    fail_scans: dict[str, int] = {}
    total_scans = 0
    for row in rows:
        total_scans += int(row["scans"] or 0)
        for key, count in (_loads(row["fail_counts"]) or {}).items():
            fail_scans[key] = fail_scans.get(key, 0) + int(count)
        if row["status"] == "expired":
            failed = (_loads(row["last_eval"]) or {}).get("failed") or []
            for key in failed:
                blockers[key] = blockers.get(key, 0) + 1

    shadows: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row["shadow_status"]:
            continue
        key = str(row["near_miss_missing"] or "?")
        item = shadows.setdefault(
            key, {"missing": key, "count": 0, "closed": 0, "wins": 0, "pnl": 0.0, "roe_sum": 0.0, "entered_later": 0}
        )
        item["count"] += 1
        if row["status"] == "entered":
            item["entered_later"] += 1
        if row["shadow_status"] == "closed":
            pnl = float(row["shadow_pnl_usd"] or 0)
            item["closed"] += 1
            item["pnl"] += pnl
            item["roe_sum"] += float(row["shadow_roe"] or 0)
            if pnl > 0:
                item["wins"] += 1
    shadow_rows = []
    for item in shadows.values():
        closed = item["closed"]
        shadow_rows.append(
            {
                "missing": item["missing"],
                "count": item["count"],
                "closed": closed,
                "wins": item["wins"],
                "win_rate": round(item["wins"] / closed * 100.0, 1) if closed else None,
                "avg_roe": round(item["roe_sum"] / closed, 1) if closed else None,
                "pnl": round(item["pnl"], 2),
                "entered_later": item["entered_later"],
            }
        )
    shadow_rows.sort(key=lambda r: -r["count"])
    return {
        "total": len(rows),
        "by_status": status_counts,
        "blockers": dict(sorted(blockers.items(), key=lambda kv: -kv[1])),
        "fail_rate": {
            key: round(count / total_scans * 100.0, 1) for key, count in fail_scans.items()
        }
        if total_scans
        else {},
        "shadows": shadow_rows,
        "shadow_margin": config.PAPER_START_BALANCE_USD * config.PAPER_MARGIN_PCT / 100.0,
    }


def list_trades(conn: sqlite3.Connection, status: str = "closed", limit: int = 300) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    order = "closed_at" if status == "closed" else "opened_at"
    rows = conn.execute(
        f"SELECT * FROM paper_trades WHERE status = ? ORDER BY {order} DESC LIMIT ?",
        (status, limit),
    )
    out = []
    for row in rows:
        item = dict(row)
        item["entry"] = _loads(item.pop("entry_json", None))
        item["exit"] = _loads(item.pop("exit_json", None))
        out.append(item)
    return out


def list_candidates(conn: sqlite3.Connection, limit: int = 300) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM paper_candidates WHERE status != 'watching' ORDER BY COALESCE(ended_at, updated_at) DESC LIMIT ?",
        (limit,),
    )
    out = []
    for row in rows:
        item = dict(row)
        item["last_eval"] = _loads(item.get("last_eval"))
        item["fail_counts"] = _loads(item.get("fail_counts"))
        item.pop("near_miss_json", None)
        out.append(item)
    return out


def _loads(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
