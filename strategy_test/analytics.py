"""Срезы: что чаще совпадает в прибыльных и убыточных сигналах."""

from __future__ import annotations

import json
from typing import Any


def compute_analytics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows — закрытые сигналы с полем checks (dict[str,bool])."""
    closed = [r for r in rows if r.get("outcome") and r.get("exit_ts")]
    wins = [r for r in closed if (r.get("pnl_pct") or 0) > 0]
    losses = [r for r in closed if (r.get("pnl_pct") or 0) <= 0]

    def factor_stats(subset: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if not subset:
            return {}
        keys: set[str] = set()
        for r in subset:
            checks = r.get("checks") or {}
            if isinstance(checks, str):
                checks = json.loads(checks)
            keys.update(checks.keys())
        result: dict[str, dict[str, Any]] = {}
        n = len(subset)
        for key in sorted(keys):
            hit = 0
            for r in subset:
                checks = r.get("checks") or {}
                if isinstance(checks, str):
                    checks = json.loads(checks)
                if checks.get(key):
                    hit += 1
            result[key] = {"count": hit, "pct": round(100 * hit / n, 1)}
        return result

    win_rate = round(100 * len(wins) / len(closed), 1) if closed else 0.0
    by_grade: dict[str, dict[str, Any]] = {}
    for g in ("A", "B", "C"):
        sub = [r for r in closed if r.get("grade") == g]
        if not sub:
            continue
        w = sum(1 for r in sub if (r.get("pnl_pct") or 0) > 0)
        by_grade[g] = {"trades": len(sub), "win_rate": round(100 * w / len(sub), 1)}

    return {
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "by_grade": by_grade,
        "factors_wins": factor_stats(wins),
        "factors_losses": factor_stats(losses),
    }
