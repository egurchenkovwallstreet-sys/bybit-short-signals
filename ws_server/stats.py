"""Цифры для вкладки «Статистика». Считает по журналу SQLite, сам журнал не меняет.

Win Rate = прибыльные / все закрытые × 100.
Profit Factor = сумма прибыльных P&L / модуль суммы убыточных.
Средняя доходность = сумма P&L / количество.
Max Drawdown = наибольшая просадка кривой капитала от пика.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def empty_stats() -> dict[str, Any]:
    return {
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "avg_return": 0.0,
        "max_drawdown": 0.0,
        "count": 0,
        "equity": [],
        "rows": [],
        "demo": False,
    }


def compute_stats(path: Path | str) -> dict[str, Any]:
    database = Path(path)
    if not database.is_file():
        return empty_stats()
    try:
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
    except sqlite3.Error:
        return empty_stats()
    try:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'signals'"
        ).fetchone()
        if tables is None:
            return empty_stats()
        closed = connection.execute(
            """
            SELECT symbol, status, outcome, pnl_pct, rating, created_at, exit_at, entry_price
            FROM signals
            WHERE outcome IS NOT NULL
            ORDER BY COALESCE(exit_at, created_at)
            """
        ).fetchall()
        count_row = connection.execute("SELECT COUNT(*) AS n FROM signals").fetchone()
    except sqlite3.Error:
        return empty_stats()
    finally:
        connection.close()

    pnls = [float(row["pnl_pct"]) for row in closed if row["pnl_pct"] is not None]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = 3.0
    else:
        profit_factor = 0.0
    win_rate = (len(wins) / len(pnls) * 100.0) if pnls else 0.0
    avg_return = (sum(pnls) / len(pnls)) if pnls else 0.0
    equity = _equity(pnls)
    return {
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_return": round(avg_return, 2),
        "max_drawdown": round(_max_drawdown(equity), 2),
        "count": int(count_row["n"] if count_row else 0),
        "equity": equity,
        "rows": [
            {
                "symbol": row["symbol"],
                "status": row["status"],
                "outcome": row["outcome"],
                "pnl_pct": row["pnl_pct"],
                "rating": row["rating"],
                "created_at": row["created_at"],
                "entry_price": row["entry_price"],
            }
            for row in closed
        ],
        "demo": False,
    }


def _equity(pnls: list[float]) -> list[float]:
    equity = [100.0]
    for value in pnls:
        equity.append(equity[-1] + value)
    return equity


def _max_drawdown(equity: list[float]) -> float:
    """Просадка в процентах от пика кривой."""
    peak = equity[0] if equity else 0.0
    worst = 0.0
    for value in equity:
        if value > peak:
            peak = value
        if peak > 0:
            drawdown = (peak - value) / peak * 100.0
            if drawdown > worst:
                worst = drawdown
    return worst
