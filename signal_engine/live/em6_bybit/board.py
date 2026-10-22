"""Снимок вкладки EMA6 Bybit: биржа + претенденты (REST при необходимости)."""

from __future__ import annotations

import time
from typing import Any

import config
from signal_engine.live.em6_bybit.broker import Em6BybitBroker
from signal_engine.live.em6_bybit.grid_entry import CandidateWatch, band_lo, stretch_column_label
from signal_engine.live.em6_bybit.history import (
    load_closed_for_dashboard,
    summary_from_closed,
)
from signal_engine.live.em6_bybit.rest_stretch import scan_top_stretches
from signal_engine.live.em6_bybit.stops import (
    em6_bybit_active_trail_roe_pct,
    trail_roe_pct_from_trailing_distance,
)
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
        trail_dist = float(pos.get("trailing_stop") or 0)
        target = em6_bybit_active_trail_roe_pct(roe)
        exchange_trail = (
            trail_roe_pct_from_trailing_distance(mark, trail_dist)
            if mark > 0 and trail_dist > 0
            else 0.0
        )
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
                "trail_roe_target": round(target, 4),
                "trail_roe_exchange": round(exchange_trail, 4),
                "trail_roe_pct": round(exchange_trail if exchange_trail > 0 else target, 4),
                "trail_armed": roe + 1e-6 >= config.em6_bybit_trail_arm_roe(),
                "source": "bybit",
                "grid_levels": [],
                "ema60": 0.0,
            }
        )
    return rows


def _candidate_views_from_rest(broker: Em6BybitBroker) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now_ms = int(time.time() * 1000)
    try:
        hits = scan_top_stretches(broker._client(), symbol_limit=80)
    except Exception:
        return [], []
    views: list[dict[str, Any]] = []
    by_column: dict[str, list[dict[str, Any]]] = {}
    for sym, side, stretch, ema, _price in hits[: config.EM6_BYBIT_TOP_CANDIDATES]:
        w = CandidateWatch(symbol=sym, side=side, since_ms=now_ms)
        w.ema60 = ema
        w.last_stretch = stretch
        w.peak_stretch = stretch
        w.last_band_lo = band_lo(stretch)
        v = w.to_view()
        col = stretch_column_label(stretch)
        v["stretch_column"] = col
        views.append(v)
        by_column.setdefault(col, []).append(v)
    columns = [
        {"label": label, "candidates": by_column[label]}
        for label in sorted(by_column.keys(), key=lambda s: float(s.split("–")[0]), reverse=True)
    ]
    return views, columns


def snapshot_from_exchange(*, closed_limit: int = 200) -> dict[str, Any]:
    broker = Em6BybitBroker()
    wallet = {"equity": 0.0, "available": 0.0}
    positions: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    candidate_columns: list[dict[str, Any]] = []
    if broker.configured():
        try:
            wallet = broker.wallet_usdt()
        except Exception:
            pass
        try:
            positions = broker.linear_positions()
        except Exception:
            pass
        candidates, candidate_columns = _candidate_views_from_rest(broker)
    open_rows = _open_rows_from_positions(positions)
    syms = [p["symbol"] for p in positions]
    closed = load_closed_for_dashboard(
        broker, symbol_hints=syms, limit=min(closed_limit, 200)
    )
    unrealized = sum(float(r.get("unrealised_pnl") or 0) for r in open_rows)
    closed_stats = summary_from_closed(closed)
    n = int(closed_stats["closed_trades"])
    pnl = float(closed_stats["total_pnl_closed"])
    wins_rate = float(closed_stats["win_rate"])
    avail = round(float(wallet.get("available") or 0), 2)
    return {
        "summary": {
            "label": "EMA6 Bybit Demo",
            "wallet_equity": avail,
            "wallet_available": avail,
            "margin_usd": config.em6_bybit_margin_usd(),
            "leverage": config.em6_bybit_leverage(),
            "notional_usd": round(
                config.em6_bybit_margin_usd() * config.em6_bybit_leverage(), 2
            ),
            "open_trades": len(open_rows),
            "closed_trades": n,
            "win_rate": wins_rate,
            "total_pnl_closed": round(pnl, 2),
            "total_unrealised_pnl": round(unrealized, 2),
            "watch_count": len(candidates),
            "data_source": "bybit" if broker.configured() else "local",
        },
        "candidates": candidates,
        "candidate_columns": candidate_columns,
        "open_trades": open_rows,
        "closed_trades": closed,
    }


def _merge_open_with_candidates(
    rows: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_sym = {str(c["symbol"]): c for c in candidates if c.get("symbol")}
    out: list[dict[str, Any]] = []
    for row in rows:
        sym = str(row.get("symbol") or "")
        cand = by_sym.get(sym)
        if not cand:
            out.append(row)
            continue
        merged = dict(row)
        if not merged.get("ema60") and cand.get("ema60"):
            merged["ema60"] = cand["ema60"]
        if not merged.get("peak_stretch") and cand.get("peak_stretch"):
            merged["peak_stretch"] = cand["peak_stretch"]
        if not merged.get("grid_levels") and cand.get("levels"):
            merged["levels"] = cand["levels"]
        out.append(merged)
    return out


def _merge_open_with_engine(
    exchange_rows: list[dict[str, Any]], engine_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_sym = {str(r["symbol"]): r for r in engine_rows if r.get("symbol")}
    merged: list[dict[str, Any]] = []
    for er in exchange_rows:
        sym = str(er["symbol"])
        eng = by_sym.get(sym)
        if not eng:
            merged.append(er)
            continue
        row = dict(er)
        for key in (
            "grid_levels",
            "ema60",
            "peak_stretch",
            "trail_roe_pct",
            "trail_roe_target",
            "trail_roe_exchange",
            "trail_armed",
        ):
            if eng.get(key) not in (None, "", 0, 0.0, []):
                row[key] = eng[key]
        merged.append(row)
    return merged


def merge_public_snapshot(engine_cache: dict[str, Any] | None) -> dict[str, Any]:
    """Снимок движка + лёгкое обновление кошелька/позиций (без REST-скана 80 монет)."""
    if not engine_cache:
        return snapshot_from_exchange()
    out: dict[str, Any] = {
        "summary": dict(engine_cache.get("summary") or {}),
        "candidates": list(engine_cache.get("candidates") or []),
        "candidate_columns": list(engine_cache.get("candidate_columns") or []),
        "open_trades": list(engine_cache.get("open_trades") or []),
        "closed_trades": list(engine_cache.get("closed_trades") or []),
    }
    broker = Em6BybitBroker()
    if not broker.configured():
        return out
    try:
        wallet = broker.wallet_usdt()
        avail = round(float(wallet.get("available") or 0), 2)
        out["summary"]["wallet_available"] = avail
        out["summary"]["wallet_equity"] = avail
        out["summary"]["data_source"] = "bybit"
    except Exception:
        pass
    try:
        positions = broker.linear_positions()
        ex_open = _open_rows_from_positions(positions)
        merged = _merge_open_with_engine(ex_open, out["open_trades"])
        out["open_trades"] = _merge_open_with_candidates(merged, out.get("candidates") or [])
        out["summary"]["open_trades"] = len(out["open_trades"])
        out["summary"]["total_unrealised_pnl"] = round(
            sum(float(r.get("unrealised_pnl") or 0) for r in out["open_trades"]), 2
        )
    except Exception:
        pass
    try:
        hints = [str(r["symbol"]) for r in out["open_trades"]]
        hints += [str(r["symbol"]) for r in out.get("closed_trades") or []]
        closed = load_closed_for_dashboard(broker, symbol_hints=hints, limit=200)
        out["closed_trades"] = closed
        out["summary"].update(summary_from_closed(closed))
    except Exception:
        log.exception("em6 bybit merge closed")
    return out


def snapshot_from_db_fallback() -> dict[str, Any]:
    broker = Em6BybitBroker()
    if broker.configured():
        return snapshot_from_exchange()
    closed = load_closed_for_dashboard(broker, limit=200)
    closed_stats = summary_from_closed(closed)
    store = Em6BybitStore()
    conn = store.open()
    try:
        open_rows = store.list_trades(conn, "open", 50)
        n = int(closed_stats["closed_trades"])
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
                "win_rate": closed_stats["win_rate"],
                "total_pnl_closed": closed_stats["total_pnl_closed"],
                "total_unrealised_pnl": 0.0,
                "watch_count": 0,
                "data_source": "local",
            },
            "candidates": [],
            "candidate_columns": [],
            "open_trades": open_rows,
            "closed_trades": closed,
        }
    finally:
        conn.close()
