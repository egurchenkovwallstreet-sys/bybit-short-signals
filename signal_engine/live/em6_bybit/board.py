"""Снимок вкладки EMA6 Bybit: открытые/закрытые с биржи + кошелёк."""

from __future__ import annotations

from typing import Any

import config
from signal_engine.live.em6_bybit.broker import Em6BybitBroker
from signal_engine.live.em6_bybit.stops import em6_bybit_active_trail_roe_pct
from signal_engine.live.em6_bybit.store import Em6BybitStore


def _open_rows_from_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pos in positions:
        entry = float(pos["avg_price"])
        mark = float(pos["mark_price"])
        qty = float(pos["size"])
        lev = float(pos.get("leverage") or config.em6_bybit_leverage())
        im = float(pos.get("position_im") or 0)
        margin = im if im > 0 else (qty * entry / lev if lev else 0.0)
        pv = float(pos.get("position_value") or 0)
        notional = pv if pv > 0 else qty * mark
        upnl = float(pos.get("unrealised_pnl") or 0)
        roe = (upnl / margin * 100.0) if margin > 0 else 0.0
        max_roe = roe
        rows.append(
            {
                "symbol": pos["symbol"],
                "side": pos["side"],
                "entry_price": entry,
                "mark_price": mark,
                "qty": qty,
                "margin": round(margin, 4),
                "leverage": int(lev),
                "notional_usd": round(notional, 2),
                "unrealised_pnl": round(upnl, 4),
                "roe_pct": round(roe, 2),
                "stop_loss": float(pos.get("stop_loss") or 0),
                "trailing_stop": float(pos.get("trailing_stop") or 0),
                "max_roe": round(max_roe, 2),
                "opened_at": int(pos.get("open_time_ms") or 0),
                "trail_roe_pct": em6_bybit_active_trail_roe_pct(max_roe),
                "trail_armed": max_roe + 1e-6 >= config.em6_bybit_trail_arm_roe(),
                "source": "bybit",
                "grid_levels": [],
                "ema60": 0.0,
            }
        )
    return rows


def snapshot_from_exchange(*, closed_limit: int = 200) -> dict[str, Any]:
    broker = Em6BybitBroker()
    wallet = {"equity": 0.0, "available": 0.0}
    positions: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    if broker.configured():
        try:
            wallet = broker.wallet_usdt()
        except Exception:
            pass
        try:
            positions = broker.linear_positions()
        except Exception:
            pass
        start = int(__import__("time").time() * 1000) - 90 * 86400 * 1000
        syms = [p["symbol"] for p in positions]
        try:
            closed = broker.list_recent_closed_pnl(
                start_ms=start,
                limit=min(closed_limit, 100),
                symbols=syms,
            )
        except Exception:
            closed = []
    open_rows = _open_rows_from_positions(positions)
    unrealized = sum(float(r.get("unrealised_pnl") or 0) for r in open_rows)
    wins = sum(1 for r in closed if float(r.get("pnl_usd") or 0) > 0)
    n = len(closed)
    pnl = sum(float(r.get("pnl_usd") or 0) for r in closed)
    return {
        "summary": {
            "label": "EMA6 Bybit Demo",
                "wallet_equity": round(float(wallet.get("available") or 0), 2),
                "wallet_available": round(float(wallet.get("available") or 0), 2),
            "margin_usd": config.em6_bybit_margin_usd(),
            "leverage": config.em6_bybit_leverage(),
            "notional_usd": round(
                config.em6_bybit_margin_usd() * config.em6_bybit_leverage(), 2
            ),
            "open_trades": len(open_rows),
            "closed_trades": n,
            "win_rate": round(100.0 * wins / n, 1) if n else 0.0,
            "total_pnl_closed": round(pnl, 2),
            "total_unrealised_pnl": round(unrealized, 2),
            "data_source": "bybit" if broker.configured() else "local",
        },
        "candidates": [],
        "candidate_columns": [],
        "open_trades": open_rows,
        "closed_trades": closed,
    }


def snapshot_from_db_fallback() -> dict[str, Any]:
    broker = Em6BybitBroker()
    if broker.configured():
        ex = snapshot_from_exchange()
        if ex.get("open_trades") or ex.get("closed_trades"):
            return ex
    store = Em6BybitStore()
    conn = store.open()
    try:
        closed = store.list_trades(conn, "closed", 200)
        open_rows = store.list_trades(conn, "open", 50)
        wins = sum(1 for r in closed if float(r.get("pnl_usd") or 0) > 0)
        n = len(closed)
        pnl = sum(float(r.get("pnl_usd") or 0) for r in closed)
        return {
            "summary": {
                "label": "EMA6 Bybit Demo",
                "wallet_equity": 0.0,
                "wallet_available": 0.0,
                "margin_usd": config.em6_bybit_margin_usd(),
                "leverage": config.em6_bybit_leverage(),
                "notional_usd": round(
                    config.em6_bybit_margin_usd() * config.em6_bybit_leverage(), 2
                ),
                "open_trades": len(open_rows),
                "closed_trades": n,
                "win_rate": round(100.0 * wins / n, 1) if n else 0.0,
                "total_pnl_closed": round(pnl, 2),
                "total_unrealised_pnl": 0.0,
                "data_source": "local",
            },
            "candidates": [],
            "candidate_columns": [],
            "open_trades": open_rows,
            "closed_trades": closed,
        }
    finally:
        conn.close()
