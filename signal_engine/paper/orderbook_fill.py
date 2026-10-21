"""Исполнение market-ордера по стакану: не более N уровней цены (em6r)."""

from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass(frozen=True)
class BookFillResult:
    ok: bool
    avg_price: float
    levels_used: int
    filled_qty: float
    slippage_bps: float
    reason: str | None = None


def _levels_sorted(side: str, bids: dict[float, float], asks: dict[float, float]) -> list[tuple[float, float]]:
    """side: buy — съедаем ask; sell — bid."""
    if side == "buy":
        return sorted(((p, s) for p, s in asks.items() if s > 0), key=lambda x: x[0])
    return sorted(((p, s) for p, s in bids.items() if s > 0), key=lambda x: x[0], reverse=True)


def simulate_market_fill(
    action: str,
    qty: float,
    bids: dict[float, float],
    asks: dict[float, float],
    *,
    max_levels: int | None = None,
    ref_price: float | None = None,
) -> BookFillResult:
    """
    action: buy | sell (действие трейдера).
    qty: объём в базовой монете (как Position.qty).
    """
    if qty <= 0:
        return BookFillResult(False, 0.0, 0, 0.0, 0.0, "qty<=0")
    max_lv = int(max_levels or config.PAPER_EM6R_BOOK_MAX_LEVELS)
    levels = _levels_sorted(action, bids, asks)
    if not levels:
        return BookFillResult(False, 0.0, 0, 0.0, 0.0, "empty_book")

    remaining = qty
    cost = 0.0
    filled = 0.0
    levels_used = 0
    prev_price: float | None = None
    best = levels[0][0]

    for price, size in levels:
        if remaining <= 1e-12:
            break
        if price != prev_price:
            levels_used += 1
            prev_price = price
            if levels_used > max_lv:
                return BookFillResult(
                    False,
                    0.0,
                    levels_used - 1,
                    filled,
                    0.0,
                    f"need_more_than_{max_lv}_levels",
                )
        take = min(float(size), remaining)
        cost += take * price
        filled += take
        remaining -= take

    if remaining > qty * 1e-6:
        return BookFillResult(
            False,
            0.0,
            levels_used,
            filled,
            0.0,
            "insufficient_depth_in_levels",
        )

    avg = cost / filled
    ref = ref_price if ref_price and ref_price > 0 else best
    if action == "buy":
        slip_bps = (avg - ref) / ref * 10_000.0
    else:
        slip_bps = (ref - avg) / ref * 10_000.0
    return BookFillResult(True, avg, levels_used, filled, slip_bps, None)


def entry_action_for_side(trade_side: str) -> str:
    return "buy" if trade_side == "long" else "sell"


def exit_action_for_side(trade_side: str) -> str:
    return "sell" if trade_side == "long" else "buy"


def book_fresh(book_ts: int | None, now_ms: int) -> bool:
    if not book_ts:
        return False
    return now_ms - int(book_ts) <= int(config.PAPER_EM6R_BOOK_MAX_AGE_MS)


def simulate_entry_fill(
    trade_side: str,
    qty: float,
    state,
    now_ms: int,
) -> BookFillResult:
    if not book_fresh(getattr(state, "book_ts", None), now_ms):
        return BookFillResult(False, 0.0, 0, 0.0, 0.0, "stale_book")
    ref = float(state.last_price or state.bid1_price or state.ask1_price or 0)
    action = entry_action_for_side(trade_side)
    return simulate_market_fill(
        action,
        qty,
        state.book_bids,
        state.book_asks,
        ref_price=ref,
    )


def simulate_exit_fill(trade_side: str, qty: float, state, now_ms: int) -> BookFillResult:
    if not book_fresh(getattr(state, "book_ts", None), now_ms):
        return BookFillResult(False, 0.0, 0, 0.0, 0.0, "stale_book")
    ref = float(state.last_price or 0)
    action = exit_action_for_side(trade_side)
    return simulate_market_fill(
        action,
        qty,
        state.book_bids,
        state.book_asks,
        ref_price=ref,
    )
