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

    def slice_stats(key: str, values: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for val in values:
            sub = [r for r in closed if str(r.get(key) or "") == val]
            if not sub:
                continue
            w = sum(1 for r in sub if (r.get("pnl_pct") or 0) > 0)
            pnls = [float(r.get("pnl_pct") or 0) for r in sub]
            out[val] = {
                "trades": len(sub),
                "win_rate": round(100 * w / len(sub), 1),
                "avg_pnl": round(sum(pnls) / len(pnls), 2),
            }
        return out

    exit_reasons: dict[str, int] = {}
    for r in closed:
        reason = str(r.get("exit_reason") or "—")
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    avg_win = round(sum(float(r.get("pnl_pct") or 0) for r in wins) / len(wins), 2) if wins else 0.0
    avg_loss = round(sum(float(r.get("pnl_pct") or 0) for r in losses) / len(losses), 2) if losses else 0.0
    open_count = sum(1 for r in rows if r.get("exit_ts") is None)

    equity: list[dict[str, Any]] = []
    cum = 0.0
    for r in sorted(closed, key=lambda x: int(x.get("exit_ts") or 0)):
        cum += float(r.get("pnl_pct") or 0)
        equity.append(
            {
                "id": int(r.get("id") or 0),
                "exit_ts": int(r.get("exit_ts") or 0),
                "pnl_pct": round(float(r.get("pnl_pct") or 0), 2),
                "cum_pnl_pct": round(cum, 2),
            }
        )

    return {
        "total": len(rows),
        "open": open_count,
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "avg_win_pnl": avg_win,
        "avg_loss_pnl": avg_loss,
        "by_grade": by_grade,
        "by_mode": slice_stats("mode", ("intraday", "scalp")),
        "by_side": slice_stats("side", ("long", "short")),
        "exit_reasons": exit_reasons,
        "equity": equity[-80:],
        "factors_wins": factor_stats(wins),
        "factors_losses": factor_stats(losses),
    }
