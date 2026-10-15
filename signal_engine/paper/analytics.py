"""Статистика теста стратегии по SQLite: сделки и кандидаты без входа."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import config

EXIT_LABELS = {"trailing_stop": "Трейлинг-стоп", "liquidation": "Ликвидация"}
MSK = timezone(timedelta(hours=3))


def msk_day_start_ms(now_ms: int) -> int:
    """Полночь текущих московских суток (МСК UTC+3, без перехода на летнее время)."""
    dt = datetime.fromtimestamp(now_ms / 1000.0, tz=MSK)
    start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)


def period_bounds(now_ms: int) -> dict[str, Any]:
    """Границы закрытых периодов в МСК: месяц с 1-го, неделя с полуночи 7 суток назад, вчера целиком."""
    dt = datetime.fromtimestamp(now_ms / 1000.0, tz=MSK)
    today = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    week = today - timedelta(days=7)
    yesterday = today - timedelta(days=1)
    return {
        "as_of": dt.strftime("%d.%m %H:%M"),
        "month": int(month.timestamp() * 1000),
        "week": int(week.timestamp() * 1000),
        "yesterday_from": int(yesterday.timestamp() * 1000),
        "yesterday_to": int(today.timestamp() * 1000),
        "labels": {
            "all": "Всё время",
            "month": f"Месяц с {month.strftime('%d.%m')}",
            "week": f"Неделя с {week.strftime('%d.%m')}",
            "yesterday": f"Вчера {yesterday.strftime('%d.%m')}",
            "now": "Сейчас открытые",
        },
    }


def compute_analytics(
    conn: sqlite3.Connection,
    balances: dict[str, float] | None = None,
    now_ms: int | None = None,
    unrealized: dict[str, float] | None = None,
) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    now_ms = int(now_ms or time.time() * 1000)
    bounds = period_bounds(now_ms)
    variants = {}
    for variant in config.PAPER_VARIANTS:
        balance = (balances or {}).get(variant)
        u = float((unrealized or {}).get(variant, 0.0)) if unrealized is not None else None
        variants[variant] = _variant_stats(conn, variant, balance, now_ms, u, bounds)
    return {
        "variants": variants,
        "candidates": _candidate_stats(conn),
        "day_start_ms": msk_day_start_ms(now_ms),
        "period_labels": bounds["labels"],
        "period_as_of": bounds["as_of"],
    }


def _variant_stats(
    conn: sqlite3.Connection,
    variant: str,
    balance: float | None,
    now_ms: int,
    unrealized: float | None,
    bounds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    closed = list(
        conn.execute(
            "SELECT * FROM paper_trades WHERE status = 'closed' AND variant = ? ORDER BY closed_at", (variant,)
        )
    )
    open_count = conn.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE status = 'open' AND variant = ?", (variant,)
    ).fetchone()[0]
    trades = _trade_stats(closed)
    trades["open"] = int(open_count)
    if balance is None:
        row = conn.execute("SELECT value FROM paper_kv WHERE key = ?", (f"balance:{variant}",)).fetchone()
        balance = float(row[0]) if row else None
    if balance is not None:
        trades["balance"] = round(balance, 2)
    trades.update(_day_stats(conn, variant, closed, now_ms, balance, unrealized))
    return {
        "trades": trades,
        "by_reason": _group(closed, lambda r: EXIT_LABELS.get(r["exit_reason"], r["exit_reason"] or "—")),
        "by_kind": _group(closed, _kind_label),
        "by_grade": _group(closed, lambda r: f"Сила {r['grade'] or 'C'}"),
        "by_btc": _group(closed, lambda r: "BTC строгий режим" if r["strict_btc"] else "BTC обычный"),
        "by_trigger": _group(closed, _trigger_label),
        "by_passed": _group(closed, _passed_label),
        "equity": _equity(conn, variant),
        "periods": _closed_periods(closed, bounds or period_bounds(now_ms)),
    }


def _pnl_pack(pnls: list[float]) -> dict[str, Any]:
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    profit = sum(wins)
    loss = sum(losses)
    return {
        "n": len(pnls),
        "wins": len(wins),
        "win_pct": round(len(wins) / len(pnls) * 100.0, 1) if pnls else None,
        "profit": round(profit, 2),
        "loss": round(loss, 2),
        "net": round(profit + loss, 2),
    }


def _closed_periods(rows: list[sqlite3.Row], bounds: dict[str, Any]) -> dict[str, Any]:
    def take(pred) -> dict[str, Any]:
        pnls = [float(r["pnl_usd"] or 0) for r in rows if r["closed_at"] and pred(int(r["closed_at"]))]
        return _pnl_pack(pnls)

    return {
        "all": take(lambda _ts: True),
        "month": take(lambda ts: ts >= int(bounds["month"])),
        "week": take(lambda ts: ts >= int(bounds["week"])),
        "yesterday": take(lambda ts: int(bounds["yesterday_from"]) <= ts < int(bounds["yesterday_to"])),
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


def _day_stats(
    conn: sqlite3.Connection,
    variant: str,
    closed: list[sqlite3.Row],
    now_ms: int,
    balance: float | None,
    unrealized: float | None,
) -> dict[str, Any]:
    start_ms = msk_day_start_ms(now_ms)
    today = [r for r in closed if r["closed_at"] and int(r["closed_at"]) >= start_ms]
    closed_pnl = sum(float(r["pnl_usd"] or 0) for r in today)
    sod_row = conn.execute(
        "SELECT equity FROM paper_equity_v WHERE variant = ? AND ts < ? ORDER BY ts DESC LIMIT 1",
        (variant, start_ms),
    ).fetchone()
    if sod_row is not None:
        sod_eq = float(sod_row["equity"])
    else:
        sod_eq = float(config.PAPER_START_BALANCE_USD)
    if unrealized is not None and balance is not None:
        equity = float(balance) + float(unrealized)
    else:
        last = conn.execute(
            "SELECT equity FROM paper_equity_v WHERE variant = ? ORDER BY ts DESC LIMIT 1",
            (variant,),
        ).fetchone()
        equity = float(last["equity"]) if last is not None else (float(balance) if balance is not None else sod_eq)
    day_pnl = equity - sod_eq
    day_pct = (day_pnl / sod_eq * 100.0) if sod_eq else 0.0
    return {
        "day_pnl": round(day_pnl, 2),
        "day_pnl_pct": round(day_pct, 2),
        "day_pnl_closed": round(closed_pnl, 2),
        "day_trades": len(today),
        "day_wins": sum(1 for r in today if float(r["pnl_usd"] or 0) > 0),
        "day_start_equity": round(sod_eq, 2),
        "day_start_ms": start_ms,
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


def _kind_label(row: sqlite3.Row) -> str:
    kind = str(row["kind"] or "")
    if kind == "css":
        return "Cursor SS"
    if str(kind).startswith("sc10"):
        return "Скальп 10"
    if kind == "growth":
        return "Лонг роста"
    return "Короткий памп" if kind == "short" else "Длинный памп"


def _trigger_label(row: sqlite3.Row) -> str:
    entry = _loads(row["entry_json"])
    trigger = ((entry.get("metrics") or {}).get("pump") or {}).get("trigger") or "?"
    return {
        "4h": "Рост за ≤4 ч",
        "24h": "Рост за 24 ч",
        "7d": "Рост за 7 д",
        "14d": "Рост за 14 д",
        "fast": "Быстрый памп",
    }.get(trigger, trigger)


def _passed_label(row: sqlite3.Row) -> str:
    entry = _loads(row["entry_json"])
    count = entry.get("passed_count")
    if count is None:
        return "?"
    return f"Условий {count}/{len(entry.get('checks') or {}) or 9}"


def _equity(conn: sqlite3.Connection, variant: str) -> list[list[float]]:
    rows = conn.execute(
        "SELECT ts, balance, equity FROM paper_equity_v WHERE variant = ? ORDER BY ts DESC LIMIT 2000", (variant,)
    ).fetchall()
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


def list_trades(
    conn: sqlite3.Connection, status: str = "closed", limit: int = 300, variant: str | None = None
) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    order = "closed_at" if status == "closed" else "opened_at"
    if variant:
        rows = conn.execute(
            f"SELECT * FROM paper_trades WHERE status = ? AND variant = ? ORDER BY {order} DESC LIMIT ?",
            (status, variant, limit),
        )
    else:
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
        try:
            item["variants"] = json.loads(item.get("variants") or "[]")
        except (TypeError, ValueError):
            item["variants"] = []
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
