"""Переигрыш сделок Пылесос 15/5 по свечам: сторона, стоп −10% ROE, трейл пик − 10 п.п."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import config
from signal_engine.paper.position import Position
from signal_engine.paper.trade_side import entry_from_raw, resolve_trade_side


Bar = tuple[int, float, float, float, float]  # ts, open, high, low, close


@dataclass
class ReplayResult:
    trade_id: int
    symbol: str
    side: str
    skipped: bool
    status: str
    reason: str | None
    opened_at: int
    closed_at: int | None
    exit_price: float | None
    pnl_usd: float
    roe_pct: float
    max_roe: float
    min_roe: float
    stop_price: float
    liq_price: float
    best_price: float
    worst_price: float
    last_price: float
    margin: float
    entry_price: float
    entry_fee: float
    funding_paid: float
    exit_fee: float
    leverage: int


def _row_side(row: Any) -> str:
    keys = row.keys() if hasattr(row, "keys") else []
    side_col = row["side"] if keys and "side" in keys else None
    return resolve_trade_side(
        side=side_col,
        kind=str(row["kind"] or ""),
        variant=str(row["variant"] or ""),
        entry=entry_from_raw(row["entry_json"] if keys and "entry_json" in keys else None),
    )


def replay_position_on_bars(
    *,
    symbol: str,
    side: str,
    opened_at: int,
    entry_price: float,
    margin: float,
    leverage: int,
    bars: Iterable[Bar],
    now_ms: int,
    variant: str,
    funding_paid: float = 0.0,
    entry_fee: float | None = None,
) -> tuple[Position, str | None, int | None]:
    pos = Position(
        symbol=symbol,
        opened_at=int(opened_at),
        entry_price=float(entry_price),
        margin=float(margin),
        leverage=int(leverage),
        funding_paid=float(funding_paid or 0.0),
        side=side,
        stop_style=config.paper_stop_style(variant),
    )
    if entry_fee is not None and entry_fee > 0:
        pos.entry_fee = float(entry_fee)
    closed_at: int | None = None
    reason: str | None = None
    for ts, _o, high, low, close in bars:
        t = int(ts)
        if t < opened_at:
            continue
        if t > now_ms:
            break
        reason = pos.update(float(low), float(high), float(close))
        if reason:
            closed_at = t
            break
    return pos, reason, closed_at


def _result_from_pos(
    row: Any,
    side: str,
    pos: Position,
    reason: str | None,
    closed_at: int | None,
    *,
    skipped: bool = False,
) -> ReplayResult:
    if skipped:
        entry = float(row["entry_price"])
        return ReplayResult(
            trade_id=int(row["id"]),
            symbol=str(row["symbol"]),
            side=side,
            skipped=True,
            status="closed",
            reason="слот занят",
            opened_at=int(row["opened_at"]),
            closed_at=int(row["opened_at"]),
            exit_price=entry,
            pnl_usd=0.0,
            roe_pct=0.0,
            max_roe=0.0,
            min_roe=0.0,
            stop_price=float(row["stop_price"] or entry),
            liq_price=float(pos.liq_price),
            best_price=entry,
            worst_price=entry,
            last_price=entry,
            margin=float(row["margin"]),
            entry_price=entry,
            entry_fee=float(row["entry_fee"] or 0),
            funding_paid=float(row["funding_paid"] or 0),
            exit_fee=0.0,
            leverage=int(row["leverage"] or config.PAPER_LEVERAGE),
        )
    if reason:
        packed = pos.close_result(reason)
        return ReplayResult(
            trade_id=int(row["id"]),
            symbol=str(row["symbol"]),
            side=side,
            skipped=False,
            status="closed",
            reason=reason,
            opened_at=int(row["opened_at"]),
            closed_at=int(closed_at or row["opened_at"]),
            exit_price=float(packed["exit_price"]),
            pnl_usd=float(packed["pnl_usd"]),
            roe_pct=float(packed["roe_pct"]),
            max_roe=pos.max_roe(),
            min_roe=pos.min_roe(),
            stop_price=pos.stop_price,
            liq_price=pos.liq_price,
            best_price=pos.best_price,
            worst_price=pos.worst_price,
            last_price=pos.last_price,
            margin=pos.margin,
            entry_price=pos.entry_price,
            entry_fee=pos.entry_fee,
            funding_paid=pos.funding_paid,
            exit_fee=float(packed["exit_fee"]),
            leverage=pos.leverage,
        )
    return ReplayResult(
        trade_id=int(row["id"]),
        symbol=str(row["symbol"]),
        side=side,
        skipped=False,
        status="open",
        reason=None,
        opened_at=int(row["opened_at"]),
        closed_at=None,
        exit_price=None,
        pnl_usd=0.0,
        roe_pct=pos.net_roe(pos.last_price),
        max_roe=pos.max_roe(),
        min_roe=pos.min_roe(),
        stop_price=pos.stop_price,
        liq_price=pos.liq_price,
        best_price=pos.best_price,
        worst_price=pos.worst_price,
        last_price=pos.last_price or pos.entry_price,
        margin=pos.margin,
        entry_price=pos.entry_price,
        entry_fee=pos.entry_fee,
        funding_paid=pos.funding_paid,
        exit_fee=0.0,
        leverage=pos.leverage,
    )


def replay_variant_trades(
    rows: list[Any],
    bars_by_symbol: dict[str, list[Bar]],
    now_ms: int,
) -> list[ReplayResult]:
    """Порядок открытия, один слот на монету: пока сделка жива, повторный вход отбрасывается."""
    ordered = sorted(rows, key=lambda r: (int(r["opened_at"] or 0), int(r["id"])))
    free_at: dict[str, int] = {}
    out: list[ReplayResult] = []
    for row in ordered:
        symbol = str(row["symbol"])
        opened_at = int(row["opened_at"])
        side = _row_side(row)
        variant = str(row["variant"] or "")
        if free_at.get(symbol, 0) > opened_at:
            dummy = Position(
                symbol=symbol,
                opened_at=opened_at,
                entry_price=float(row["entry_price"]),
                margin=float(row["margin"]),
                leverage=int(row["leverage"] or config.PAPER_LEVERAGE),
                side=side,
                stop_style=config.paper_stop_style(variant),
            )
            out.append(_result_from_pos(row, side, dummy, None, None, skipped=True))
            continue
        pos, reason, closed_at = replay_position_on_bars(
            symbol=symbol,
            side=side,
            opened_at=opened_at,
            entry_price=float(row["entry_price"]),
            margin=float(row["margin"]),
            leverage=int(row["leverage"] or config.PAPER_LEVERAGE),
            bars=bars_by_symbol.get(symbol) or [],
            now_ms=now_ms,
            variant=variant,
            funding_paid=float(row["funding_paid"] or 0),
            entry_fee=float(row["entry_fee"] or 0) or None,
        )
        item = _result_from_pos(row, side, pos, reason, closed_at)
        free_at[symbol] = int(item.closed_at) if item.status == "closed" else now_ms + 1
        out.append(item)
    return out


def recompute_balances(results: list[ReplayResult], start: float) -> list[tuple[ReplayResult, float, float]]:
    """Закрытия по времени — цепочка balance_before / after."""
    closed = [r for r in results if r.status == "closed"]
    closed.sort(key=lambda r: (int(r.closed_at or r.opened_at), r.trade_id))
    bal = float(start)
    chain: list[tuple[ReplayResult, float, float]] = []
    for item in closed:
        before = bal
        bal += item.pnl_usd
        chain.append((item, before, bal))
    return chain


def _balance_before_open(results: list[ReplayResult], start: float, opened_at: int, trade_id: int) -> float:
    bal = float(start)
    for item in results:
        if item.status != "closed" or item.closed_at is None:
            continue
        if item.closed_at < opened_at or (item.closed_at == opened_at and item.trade_id < trade_id):
            bal += item.pnl_usd
    return bal


def apply_replay_to_db(db, variant: str, results: list[ReplayResult], now_ms: int) -> dict[str, Any]:
    start = float(config.PAPER_START_BALANCE_USD)
    chain = recompute_balances(results, start)
    after_by_id = {item.trade_id: (before, after) for item, before, after in chain}
    final = chain[-1][2] if chain else start

    for item in results:
        if item.status == "closed":
            before, after = after_by_id[item.trade_id]
        else:
            before = _balance_before_open(results, start, item.opened_at, item.trade_id)
            after = final
        if item.status == "open":
            db.execute(
                "UPDATE paper_trades SET status='open', side=?, closed_at=NULL, exit_price=NULL, "
                "exit_reason=NULL, exit_fee=NULL, pnl_usd=NULL, roe_pct=?, max_roe=?, min_roe=?, "
                "stop_price=?, liq_price=?, best_price=?, worst_price=?, last_price=?, "
                "balance_before=?, balance_after=NULL, exit_json=? WHERE id=?",
                (
                    item.side,
                    item.roe_pct,
                    item.max_roe,
                    item.min_roe,
                    item.stop_price,
                    item.liq_price,
                    item.best_price,
                    item.worst_price,
                    item.last_price,
                    before,
                    _exit_json(item, now_ms, replayed=True),
                    item.trade_id,
                ),
            )
            continue
        db.execute(
            "UPDATE paper_trades SET status='closed', side=?, closed_at=?, exit_price=?, "
            "exit_reason=?, exit_fee=?, pnl_usd=?, roe_pct=?, max_roe=?, min_roe=?, "
            "stop_price=?, liq_price=?, best_price=?, worst_price=?, last_price=?, "
            "balance_before=?, balance_after=?, exit_json=? WHERE id=?",
            (
                item.side,
                item.closed_at,
                item.exit_price,
                item.reason,
                item.exit_fee,
                item.pnl_usd,
                item.roe_pct,
                item.max_roe,
                item.min_roe,
                item.stop_price,
                item.liq_price,
                item.best_price,
                item.worst_price,
                item.last_price,
                before,
                after,
                _exit_json(item, now_ms, replayed=True),
                item.trade_id,
            ),
        )
    db.execute(
        "INSERT INTO paper_kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (f"balance:{variant}", str(final)),
    )
    db.commit()
    return {
        "variant": variant,
        "trades": len(results),
        "open": sum(1 for r in results if r.status == "open"),
        "closed": sum(1 for r in results if r.status == "closed"),
        "skipped": sum(1 for r in results if r.skipped),
        "balance": final,
    }


def _exit_json(item: ReplayResult, now_ms: int, *, replayed: bool) -> str:
    import json

    duration = 0
    if item.closed_at:
        duration = round((item.closed_at - item.opened_at) / 60_000)
    elif item.status == "open":
        duration = round((now_ms - item.opened_at) / 60_000)
    return json.dumps(
        {
            "duration_min": duration,
            "last_price": item.last_price,
            "best_price": item.best_price,
            "worst_price": item.worst_price,
            "funding_paid": item.funding_paid,
            "replayed": replayed,
            "side": item.side,
        },
        ensure_ascii=False,
    )
