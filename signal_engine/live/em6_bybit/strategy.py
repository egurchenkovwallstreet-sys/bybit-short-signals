"""EMA6 Bybit Demo: вход по em6r, стопы и трейл на бирже."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import config
from signal_engine.live.em6_bybit.broker import Em6BybitBroker
from signal_engine.live.em6_bybit.store import Em6BybitStore
from signal_engine.paper.ema60_stretch_detect import evaluate_ema60_stretch, stretch_passes_variant
from signal_engine.paper.position import (
    ema60_stretch_trail_stop,
    long_roe_pct,
    roe_pct,
)
from signal_engine.state import SymbolState

log = logging.getLogger(__name__)
BOARD_TYPE = "em6_bybit"
VARIANT = config.PAPER_EM6R_VARIANT


@dataclass
class LiveOpen:
    id: int
    symbol: str
    side: str
    entry_price: float
    qty: float
    margin: float
    leverage: int
    stop_price: float
    best_price: float
    worst_price: float
    opened_at: int
    last_exchange_stop: float = 0.0


@dataclass
class Em6BybitStrategy:
    store: Em6BybitStore = field(default_factory=Em6BybitStore)
    broker: Em6BybitBroker = field(default_factory=Em6BybitBroker)
    open_trades: dict[str, LiveOpen] = field(default_factory=dict)
    _conn: Any = None
    _recovered: bool = False
    _last_status_log_ms: int = 0

    def open(self) -> None:
        if not self.broker.configured():
            log.warning("EMA6 Bybit: выключен (нет Demo API ключей или EM6_BYBIT_ENABLED=0)")
            return
        self._conn = self.store.open()
        self._recover()
        log.info("EMA6 Bybit: бот активен, восстановлено позиций %s", len(self.open_trades))

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _recover(self) -> None:
        if self._recovered or self._conn is None:
            return
        self._recovered = True
        self.open_trades.clear()
        db_open = {r["symbol"]: r for r in self.store.all_open(self._conn)}
        try:
            positions = {p["symbol"]: p for p in self.broker.linear_positions()}
        except Exception:
            log.exception("em6 bybit: recover positions")
            return

        for sym, row in db_open.items():
            if sym not in positions:
                self._finalize_closed(sym, row, reason="exchange_flat")
                continue
            self._load_live(row)

        for sym, pos in positions.items():
            if sym in self.open_trades:
                continue
            side = pos["side"]
            entry = float(pos["avg_price"])
            qty = float(pos["size"])
            lev = int(pos.get("leverage") or config.PAPER_LEVERAGE)
            margin = qty * entry / lev if lev else 0.0
            stop = self._compute_stop_for(side, entry, entry, margin, qty)
            tid = self.store.insert_open(
                self._conn,
                {
                    "symbol": sym,
                    "side": side,
                    "opened_at": int(time.time() * 1000),
                    "entry_price": entry,
                    "qty": qty,
                    "margin": margin,
                    "leverage": lev,
                    "stop_price": stop,
                    "best_price": entry,
                    "worst_price": entry,
                    "entry_order_id": "recovered",
                },
            )
            live = LiveOpen(
                id=tid,
                symbol=sym,
                side=side,
                entry_price=entry,
                qty=qty,
                margin=margin,
                leverage=lev,
                stop_price=stop,
                best_price=entry,
                worst_price=entry,
                opened_at=int(time.time() * 1000),
            )
            self.open_trades[sym] = live
            self._push_stop(live)
            log.info("em6 bybit: recovered open %s %s", sym, side)

        for sym, live in list(self.open_trades.items()):
            if sym not in positions:
                row = db_open.get(sym) or {"id": live.id, "symbol": sym}
                self._finalize_closed(sym, row, reason="exchange_flat")

    def _load_live(self, row: dict[str, Any]) -> None:
        sym = str(row["symbol"])
        self.open_trades[sym] = LiveOpen(
            id=int(row["id"]),
            symbol=sym,
            side=str(row["side"]),
            entry_price=float(row["entry_price"]),
            qty=float(row["qty"]),
            margin=float(row["margin"] or 0),
            leverage=int(row["leverage"]),
            stop_price=float(row["stop_price"]),
            best_price=float(row["best_price"]),
            worst_price=float(row["worst_price"]),
            opened_at=int(row["opened_at"]),
            last_exchange_stop=float(row["last_exchange_stop"] or 0),
        )
        self._push_stop(self.open_trades[sym])

    def _entry_fee(self, entry: float, qty: float) -> float:
        return qty * entry * config.PAPER_FEE_RATE_TAKER

    def _compute_stop_for(
        self,
        side: str,
        entry: float,
        best: float,
        margin: float,
        qty: float,
    ) -> float:
        fee = self._entry_fee(entry, qty)
        return ema60_stretch_trail_stop(
            entry,
            best,
            config.PAPER_LEVERAGE,
            margin=margin,
            entry_fee=fee,
            funding_paid=0.0,
            side=side,
            variant=VARIANT,
        )

    def _max_roe(self, live: LiveOpen) -> float:
        if live.side == "long":
            return long_roe_pct(live.entry_price, live.best_price, live.leverage)
        return roe_pct(live.entry_price, live.best_price, live.leverage)

    def _min_roe(self, live: LiveOpen) -> float:
        if live.side == "long":
            return long_roe_pct(live.entry_price, live.worst_price, live.leverage)
        return roe_pct(live.entry_price, live.worst_price, live.leverage)

    def _push_stop(self, live: LiveOpen) -> None:
        try:
            self.broker.set_stop_loss(live.symbol, live.stop_price)
            live.last_exchange_stop = live.stop_price
            self.store.update_open(
                self._conn,
                live.id,
                {"stop_price": live.stop_price, "last_exchange_stop": live.stop_price},
            )
        except Exception:
            log.exception("em6 bybit: set stop %s", live.symbol)

    def _stop_changed(self, live: LiveOpen, new_stop: float) -> bool:
        if live.last_exchange_stop <= 0:
            return True
        ref = max(abs(live.entry_price), 1e-12)
        return abs(new_stop - live.last_exchange_stop) / ref > 0.00005

    def _update_live(self, live: LiveOpen, state: SymbolState) -> None:
        last = float(state.last_price or live.entry_price)
        if live.side == "long":
            live.best_price = max(live.best_price, last)
            live.worst_price = min(live.worst_price, last)
        else:
            live.best_price = min(live.best_price, last)
            live.worst_price = max(live.worst_price, last)
        new_stop = self._compute_stop_for(
            live.side, live.entry_price, live.best_price, live.margin, live.qty
        )
        live.stop_price = new_stop
        fields = {
            "best_price": live.best_price,
            "worst_price": live.worst_price,
            "stop_price": live.stop_price,
            "max_roe": self._max_roe(live),
            "min_roe": self._min_roe(live),
        }
        self.store.update_open(self._conn, live.id, fields)
        if self._stop_changed(live, new_stop):
            self._push_stop(live)

    def _finalize_closed(self, symbol: str, row: dict[str, Any], *, reason: str) -> None:
        live = self.open_trades.pop(symbol, None)
        now = int(time.time() * 1000)
        exit_p = float(live.entry_price if live else row.get("entry_price") or 0)
        pnl = 0.0
        if live:
            if live.side == "long":
                pnl = (exit_p - live.entry_price) * live.qty
            else:
                pnl = (live.entry_price - exit_p) * live.qty
        self.store.close_trade(
            self._conn,
            int(row["id"]),
            {
                "closed_at": now,
                "exit_price": exit_p,
                "exit_reason": reason,
                "pnl_usd": pnl,
                "roe_pct": (pnl / live.margin * 100.0) if live and live.margin > 0 else 0,
                "max_roe": self._max_roe(live) if live else row.get("max_roe"),
                "min_roe": self._min_roe(live) if live else row.get("min_roe"),
                "stop_price": live.stop_price if live else row.get("stop_price"),
                "best_price": live.best_price if live else row.get("best_price"),
                "worst_price": live.worst_price if live else row.get("worst_price"),
                "exit_json": {"sync": reason},
            },
        )

    def _sync_closures(self) -> None:
        try:
            on_ex = {p["symbol"] for p in self.broker.linear_positions()}
        except Exception:
            log.exception("em6 bybit: positions poll")
            return
        for sym in list(self.open_trades.keys()):
            if sym not in on_ex:
                row = self.store.open_by_symbol(self._conn, sym) or {"id": self.open_trades[sym].id, "symbol": sym}
                self._finalize_closed(sym, row, reason="trailing_stop")

    def _try_open(self, symbol: str, state: SymbolState, now_ms: int, wallet_avail: float) -> None:
        if symbol in self.open_trades:
            return
        ev = evaluate_ema60_stretch(state, now_ms)
        if not ev.passed or not stretch_passes_variant(ev, VARIANT):
            return
        min_turn = config.ema60_stretch_min_turnover_usdt(VARIANT)
        if min_turn is not None:
            turn = state.turnover_24h_usdt
            if turn is None or float(turn) < min_turn:
                return
        price = float(state.last_price or 0)
        if price <= 0:
            return
        margin = wallet_avail * config.PAPER_MARGIN_PCT / 100.0
        if margin < 1.0:
            return
        lev = config.PAPER_LEVERAGE
        qty = margin * lev / price
        side = ev.side or "short"
        stop = self._compute_stop_for(side, price, price, margin, qty)
        link = f"e6b-{symbol}-{now_ms}"[:36]
        try:
            resp = self.broker.open_market_with_stop(symbol, side, qty, stop, link)
            if resp.get("retCode") not in (0, "0", None):
                log.warning("em6 bybit open %s: %s", symbol, resp)
                return
        except Exception:
            log.exception("em6 bybit open %s", symbol)
            return
        tid = self.store.insert_open(
            self._conn,
            {
                "symbol": symbol,
                "side": side,
                "opened_at": now_ms,
                "entry_price": price,
                "qty": qty,
                "margin": margin,
                "leverage": lev,
                "stop_price": stop,
                "best_price": price,
                "worst_price": price,
                "max_roe": 0.0,
                "min_roe": 0.0,
                "entry_order_id": link,
                "last_exchange_stop": stop,
            },
        )
        self.open_trades[symbol] = LiveOpen(
            id=tid,
            symbol=symbol,
            side=side,
            entry_price=price,
            qty=qty,
            margin=margin,
            leverage=lev,
            stop_price=stop,
            best_price=price,
            worst_price=price,
            opened_at=now_ms,
            last_exchange_stop=stop,
        )
        log.info("em6 bybit OPEN %s %s margin=%.2f stop=%.6f", side, symbol, margin, stop)

    def scan(self, states: dict[str, SymbolState], now_ms: int) -> dict[str, Any]:
        if not self.broker.configured():
            return {"type": BOARD_TYPE, "timestamp": now_ms, "data": self.view(now_ms)}
        if self._conn is None:
            self.open()
        self._sync_closures()
        for sym, live in list(self.open_trades.items()):
            st = states.get(sym)
            if st is not None:
                self._update_live(live, st)
        try:
            wallet = self.broker.wallet_usdt()
            avail = float(wallet.get("available") or 0)
        except Exception:
            log.exception("em6 bybit wallet")
            avail = 0.0
        reserved = sum(t.margin for t in self.open_trades.values())
        free = max(0.0, avail - reserved)
        ema_ready = 0
        candidates = 0
        for symbol, state in states.items():
            if not state.last_price:
                continue
            ev = evaluate_ema60_stretch(state, now_ms)
            if ev.checks.get("ema_ready", {}).get("ok"):
                ema_ready += 1
            if stretch_passes_variant(ev, VARIANT):
                turn = state.turnover_24h_usdt
                if turn is not None and float(turn) >= float(
                    config.ema60_stretch_min_turnover_usdt(VARIANT) or 0
                ):
                    candidates += 1
            self._try_open(symbol, state, now_ms, free)
            if symbol in self.open_trades:
                free = max(0.0, free - self.open_trades[symbol].margin)
        if now_ms - self._last_status_log_ms >= 120_000:
            self._last_status_log_ms = now_ms
            log.info(
                "EMA6 Bybit: монет в движке %s, EMA60 готова %s, кандидатов em6r %s, открыто %s, avail $%.0f",
                len(states),
                ema_ready,
                candidates,
                len(self.open_trades),
                avail,
            )
        return {"type": BOARD_TYPE, "timestamp": now_ms, "data": self.view(now_ms)}

    def view(self, now_ms: int) -> dict[str, Any]:
        wallet = {"equity": 0.0, "available": 0.0}
        if self.broker.configured():
            try:
                wallet = self.broker.wallet_usdt()
            except Exception:
                pass
        closed: list[dict] = []
        if self._conn is not None:
            closed = self.store.list_trades(self._conn, "closed", 200)
        open_rows = []
        for live in self.open_trades.values():
            open_rows.append(
                {
                    "id": live.id,
                    "symbol": live.symbol,
                    "side": live.side,
                    "variant": "em6_bybit",
                    "entry_price": live.entry_price,
                    "margin": live.margin,
                    "leverage": live.leverage,
                    "qty": live.qty,
                    "stop_price": live.stop_price,
                    "best_price": live.best_price,
                    "worst_price": live.worst_price,
                    "max_roe": self._max_roe(live),
                    "min_roe": self._min_roe(live),
                    "opened_at": live.opened_at,
                    "exchange_stop": live.last_exchange_stop,
                }
            )
        wins = sum(1 for r in closed if float(r.get("pnl_usd") or 0) > 0)
        n_closed = len(closed)
        sum_pnl = sum(float(r.get("pnl_usd") or 0) for r in closed)
        return {
            "summary": {
                "label": "EMA6 Bybit Demo",
                "wallet_equity": round(wallet.get("equity", 0), 2),
                "wallet_available": round(wallet.get("available", 0), 2),
                "margin_pct": config.PAPER_MARGIN_PCT,
                "leverage": config.PAPER_LEVERAGE,
                "open_trades": len(open_rows),
                "closed_trades": n_closed,
                "win_rate": round(100.0 * wins / n_closed, 1) if n_closed else 0.0,
                "total_pnl_closed": round(sum_pnl, 2),
            },
            "open_trades": open_rows,
            "closed_trades": closed,
        }
