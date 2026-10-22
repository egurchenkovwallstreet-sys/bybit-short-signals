"""EMA6 Bybit Demo: сетка уровней от EMA60, вход по 1m к EMA."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import config
from signal_engine.live.em6_bybit.broker import Em6BybitBroker
from signal_engine.live.em6_bybit.grid_entry import (
    CandidateWatch,
    pick_top_candidates,
    stretch_at_price,
    stretch_column_label,
)
from signal_engine.live.em6_bybit.store import Em6BybitStore
from signal_engine.paper.ema60_stretch_detect import evaluate_ema60_stretch
from signal_engine.live.em6_bybit.grid_entry import price_at_stretch
from signal_engine.live.em6_bybit.stops import (
    em6_bybit_active_trail_roe_pct,
    em6_bybit_trailing_stop_price,
)
from signal_engine.paper.position import long_roe_pct, roe_pct
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
    last_trail_roe_pct: float = 0.0
    ema60: float = 0.0
    grid_levels: list[dict[str, float]] = field(default_factory=list)


@dataclass
class Em6BybitStrategy:
    store: Em6BybitStore = field(default_factory=Em6BybitStore)
    broker: Em6BybitBroker = field(default_factory=Em6BybitBroker)
    open_trades: dict[str, LiveOpen] = field(default_factory=dict)
    _conn: Any = None
    _recovered: bool = False
    _last_status_log_ms: int = 0
    _watch: dict[str, CandidateWatch] = field(default_factory=dict)
    _last_universe_ms: int = -1
    _last_candidate_ms: int = -1
    _last_open_ms: int = -1
    _last_peak_ms: int = -1
    _wallet_avail: float = 0.0

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
            lev = int(pos.get("leverage") or config.em6_bybit_leverage())
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
            self._ensure_trailing(live)
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
        self._ensure_trailing(self.open_trades[sym])

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
        return em6_bybit_trailing_stop_price(
            entry,
            best,
            side=side,
            margin=margin,
            entry_fee=fee,
        )

    def _max_roe(self, live: LiveOpen) -> float:
        if live.side == "long":
            return long_roe_pct(live.entry_price, live.best_price, live.leverage)
        return roe_pct(live.entry_price, live.best_price, live.leverage)

    def _min_roe(self, live: LiveOpen) -> float:
        if live.side == "long":
            return long_roe_pct(live.entry_price, live.worst_price, live.leverage)
        return roe_pct(live.entry_price, live.worst_price, live.leverage)

    def _ref_price(self, live: LiveOpen, state: SymbolState | None) -> float:
        if state is not None and state.last_price:
            return float(state.last_price)
        return live.entry_price

    def _roe_from_upnl(self, upnl: float, margin: float) -> float:
        if margin <= 0:
            return 0.0
        return upnl / margin * 100.0

    def _open_rows_from_exchange(self, positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for pos in positions:
            sym = str(pos["symbol"])
            live = self.open_trades.get(sym)
            entry = float(pos["avg_price"])
            mark = float(pos["mark_price"])
            qty = float(pos["size"])
            lev = float(pos.get("leverage") or config.em6_bybit_leverage())
            im = float(pos.get("position_im") or 0)
            margin = im if im > 0 else (qty * entry / lev if lev else 0.0)
            pv = float(pos.get("position_value") or 0)
            notional = pv if pv > 0 else qty * mark
            upnl = float(pos.get("unrealised_pnl") or 0)
            roe = self._roe_from_upnl(upnl, margin)
            max_roe = self._max_roe(live) if live else roe
            row: dict[str, Any] = {
                "id": live.id if live else None,
                "symbol": sym,
                "side": pos["side"],
                "variant": "em6_bybit",
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
                "take_profit": float(pos.get("take_profit") or 0),
                "liq_price": float(pos.get("liq_price") or 0),
                "max_roe": round(max_roe, 2),
                "min_roe": round(self._min_roe(live), 2) if live else round(min(0.0, roe), 2),
                "opened_at": int(live.opened_at if live else pos.get("open_time_ms") or 0),
                "trail_roe_pct": em6_bybit_active_trail_roe_pct(max_roe),
                "trail_armed": max_roe + 1e-6 >= config.em6_bybit_trail_arm_roe(),
                "source": "bybit",
                "ema60": live.ema60 if live else 0.0,
                "grid_levels": live.grid_levels if live else [],
            }
            rows.append(row)
        rows.sort(key=lambda r: abs(float(r.get("unrealised_pnl") or 0)), reverse=True)
        return rows

    def _closed_rows_from_exchange(self, *, limit: int = 200) -> list[dict[str, Any]]:
        start = int(time.time() * 1000) - 90 * 86400 * 1000
        syms = list(self.open_trades.keys())
        if self._conn is not None:
            for r in self.store.list_trades(self._conn, "closed", 80):
                s = str(r.get("symbol") or "")
                if s and s not in syms:
                    syms.append(s)
        return self.broker.list_recent_closed_pnl(
            start_ms=start, limit=min(limit, 100), symbols=syms
        )

    def _ensure_trailing(self, live: LiveOpen, state: SymbolState | None = None) -> None:
        ref = self._ref_price(live, state)
        peak = self._max_roe(live)
        trail_roe = em6_bybit_active_trail_roe_pct(peak)
        if (
            live.last_trail_roe_pct > 0
            and abs(trail_roe - live.last_trail_roe_pct) < 1e-6
            and live.last_exchange_stop > 0
        ):
            return
        try:
            resp = self.broker.set_trailing_stop_roe(
                live.symbol,
                ref_price=ref,
                side=live.side,
                trail_roe_pct=trail_roe,
            )
            code = resp.get("retCode") if isinstance(resp, dict) else None
            if code not in (0, "0", None):
                log.warning("em6 bybit trailing %s: %s", live.symbol, resp)
                return
            prev = live.last_trail_roe_pct
            live.last_trail_roe_pct = trail_roe
            live.last_exchange_stop = live.stop_price
            self.store.update_open(
                self._conn,
                live.id,
                {"stop_price": live.stop_price, "last_exchange_stop": live.last_exchange_stop},
            )
            if prev > 0 and abs(prev - trail_roe) > 1e-6:
                log.info(
                    "em6 bybit %s: trail %.0f%% → %.0f%% ROE (peak %.2f%%)",
                    live.symbol,
                    prev,
                    trail_roe,
                    peak,
                )
        except Exception:
            log.exception("em6 bybit: trailing %s", live.symbol)

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
        self._ensure_trailing(live, state)

    def _is_initial_stop_close(self, live: LiveOpen | None, row: dict[str, Any]) -> bool:
        arm = config.em6_bybit_trail_arm_roe()
        if live is not None:
            return self._max_roe(live) + 1e-6 < arm
        max_roe = row.get("max_roe")
        if max_roe is None:
            return False
        return float(max_roe) + 1e-6 < arm

    def _finalize_closed(self, symbol: str, row: dict[str, Any], *, reason: str) -> None:
        live = self.open_trades.pop(symbol, None)
        now = int(time.time() * 1000)
        if reason == "trailing_stop" and self._is_initial_stop_close(live, row):
            w = self._watch.setdefault(
                symbol,
                CandidateWatch(symbol=symbol, side=live.side if live else "short", since_ms=now),
            )
            w.start_cooldown(now)
            log.info("em6 bybit: %s initial stop — pause 15s", symbol)
        opened_at = int(live.opened_at if live else row.get("opened_at") or 0)
        entry_p = float(live.entry_price if live else row.get("entry_price") or 0)
        exit_p = entry_p
        pnl = 0.0
        if self.broker.configured() and opened_at and entry_p > 0:
            ex = self.broker.match_closed_pnl(
                symbol,
                opened_at,
                entry_p,
                closed_at_ms=now,
            )
            if ex and ex.get("exit_price"):
                exit_p = float(ex["exit_price"])
                pnl = float(ex.get("pnl_usd") or 0)
                if ex.get("closed_at_ms"):
                    now = int(ex["closed_at_ms"])
        if live and pnl == 0.0 and exit_p == float(row.get("entry_price") or 0):
            exit_p = float(live.stop_price or live.entry_price)
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
                row = self.store.open_by_symbol(self._conn, sym) or {
                    "id": self.open_trades[sym].id,
                    "symbol": sym,
                }
                self._finalize_closed(sym, row, reason="trailing_stop")

    def _stretch_row(
        self, symbol: str, state: SymbolState, now_ms: int
    ) -> tuple[str, str, float, float] | None:
        ev = evaluate_ema60_stretch(state, now_ms)
        if not ev.passed or ev.side not in ("long", "short"):
            return None
        min_turn = config.ema60_stretch_min_turnover_usdt(VARIANT)
        if min_turn is not None:
            turn = state.turnover_24h_usdt
            if turn is None or float(turn) < min_turn:
                return None
        ema = float(ev.metrics.get("ema60") or 0)
        stretch = float(ev.metrics.get("stretch_pct") or 0)
        if ema <= 0:
            return None
        return symbol, ev.side, stretch, ema

    @staticmethod
    def _last_closed_1m(state: SymbolState, now_ms: int) -> tuple[int, float] | None:
        for bar in reversed(state.bars_1m):
            if bar.timestamp + 60_000 <= now_ms:
                return bar.timestamp, float(bar.close)
        return None

    def _refresh_universe(self, states: dict[str, SymbolState], now_ms: int) -> None:
        rows: list[tuple[str, str, float, float]] = []
        for symbol, state in states.items():
            if not state.last_price:
                continue
            row = self._stretch_row(symbol, state, now_ms)
            if row is not None:
                rows.append(row)
        top = pick_top_candidates(rows, limit=config.EM6_BYBIT_TOP_CANDIDATES)
        keep = {s for s, _, _ in top} | set(self.open_trades.keys())
        for sym in list(self._watch.keys()):
            if sym not in keep:
                del self._watch[sym]
        for symbol, side, stretch in top:
            if symbol in self.open_trades:
                continue
            w = self._watch.get(symbol)
            if w is None:
                w = CandidateWatch(symbol=symbol, side=side, since_ms=now_ms)
                w.peak_stretch = stretch
                w.last_stretch = stretch
                w.peak_price = float(states[symbol].last_price or 0)
                self._watch[symbol] = w
            else:
                w.side = side

    def _update_peaks(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for symbol, w in self._watch.items():
            if symbol in self.open_trades:
                continue
            state = states.get(symbol)
            if state is None or not state.last_price:
                continue
            row = self._stretch_row(symbol, state, now_ms)
            if row is None:
                continue
            _, _, stretch, ema = row
            price = float(state.last_price)
            w.update_peak(now_ms, stretch, price, ema)

    def _execute_open(
        self,
        symbol: str,
        state: SymbolState,
        side: str,
        now_ms: int,
        stretch: float,
    ) -> None:
        price = float(state.last_price or 0)
        if price <= 0:
            return
        if self._wallet_avail + 1e-9 < config.em6_bybit_margin_usd():
            return
        lev = config.em6_bybit_leverage()
        w = self._watch.get(symbol)
        ema = float(w.ema60 if w and w.ema60 else 0)
        if ema <= 0:
            row = self._stretch_row(symbol, state, now_ms)
            if row:
                ema = row[3]
        grid_levels: list[dict[str, float]] = []
        if w is not None:
            for lo, hi in w.to_view().get("levels") or []:
                if side == "long":
                    p_lo = price_at_stretch(ema, side, hi)
                    p_hi = price_at_stretch(ema, side, lo)
                else:
                    p_lo = price_at_stretch(ema, side, lo)
                    p_hi = price_at_stretch(ema, side, hi)
                grid_levels.append(
                    {
                        "stretch_lo": lo,
                        "stretch_hi": hi,
                        "price_lo": p_lo,
                        "price_hi": p_hi,
                    }
                )
        link = f"e6b-{symbol}-{now_ms}"[:36]
        try:
            resp, qty, margin, notional = self.broker.open_market_fixed_notional(
                symbol, side, price, link
            )
            if resp.get("retCode") not in (0, "0", None):
                log.warning("em6 bybit open %s: %s", symbol, resp)
                return
            stop = self._compute_stop_for(side, price, price, margin, qty)
            tr = self.broker.set_trailing_stop_roe(
                symbol,
                ref_price=price,
                side=side,
                trail_roe_pct=config.em6_bybit_trail_initial_roe(),
            )
            if tr.get("retCode") not in (0, "0", None):
                log.warning("em6 bybit trailing after open %s: %s", symbol, tr)
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
        live = LiveOpen(
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
            last_trail_roe_pct=config.em6_bybit_trail_initial_roe(),
            ema60=ema,
            grid_levels=grid_levels,
        )
        self.open_trades[symbol] = live
        self._watch.pop(symbol, None)
        log.info(
            "em6 bybit OPEN %s %s notional=$%.2f margin=$%.2f stretch=%.2f trail−%.0f%% ROE",
            side,
            symbol,
            notional,
            margin,
            stretch,
            config.em6_bybit_trail_initial_roe(),
        )

    def _tick_candidates(
        self,
        states: dict[str, SymbolState],
        now_ms: int,
        on_exchange: set[str],
    ) -> None:
        for symbol, w in list(self._watch.items()):
            if symbol in self.open_trades or symbol in on_exchange:
                continue
            state = states.get(symbol)
            if state is None or not state.last_price:
                continue
            row = self._stretch_row(symbol, state, now_ms)
            if row is None:
                continue
            _, side, stretch, ema = row
            price = float(state.last_price)
            closed_1m = self._last_closed_1m(state, now_ms)
            if w.tick(now_ms, stretch, price, ema, closed_1m):
                self._execute_open(symbol, state, side, now_ms, stretch)

    def scan(self, states: dict[str, SymbolState], now_ms: int) -> dict[str, Any]:
        if not self.broker.configured():
            return {"type": BOARD_TYPE, "timestamp": now_ms, "data": self.view(now_ms)}
        if self._conn is None:
            self.open()
        try:
            wallet = self.broker.wallet_usdt()
            self._wallet_avail = float(wallet.get("available") or wallet.get("equity") or 0)
        except Exception:
            log.exception("em6 bybit wallet")

        if self._last_open_ms < 0 or now_ms - self._last_open_ms >= config.EM6_BYBIT_OPEN_TICK_MS:
            self._last_open_ms = now_ms
            self._sync_closures()
            for sym, live in list(self.open_trades.items()):
                st = states.get(sym)
                if st is not None:
                    self._update_live(live, st)

        try:
            on_exchange = {p["symbol"] for p in self.broker.linear_positions()}
        except Exception:
            log.exception("em6 bybit positions")
            on_exchange = set()

        if self._last_universe_ms < 0 or now_ms - self._last_universe_ms >= config.EM6_BYBIT_UNIVERSE_SCAN_MS:
            self._last_universe_ms = now_ms
            self._refresh_universe(states, now_ms)

        if self._last_peak_ms < 0 or now_ms - self._last_peak_ms >= config.EM6_BYBIT_PEAK_TICK_MS:
            self._last_peak_ms = now_ms
            self._update_peaks(states, now_ms)

        if self._last_candidate_ms < 0 or now_ms - self._last_candidate_ms >= config.EM6_BYBIT_CANDIDATE_TICK_MS:
            self._last_candidate_ms = now_ms
            self._tick_candidates(states, now_ms, on_exchange)

        if now_ms - self._last_status_log_ms >= 120_000:
            self._last_status_log_ms = now_ms
            log.info(
                "EMA6 Bybit: претендентов %s, открыто %s, avail $%.0f",
                len(self._watch),
                len(self.open_trades),
                self._wallet_avail,
            )
        return {"type": BOARD_TYPE, "timestamp": now_ms, "data": self.view(now_ms)}

    def view(self, now_ms: int) -> dict[str, Any]:
        wallet = {"equity": 0.0, "available": 0.0}
        positions: list[dict[str, Any]] = []
        if self.broker.configured():
            try:
                wallet = self.broker.wallet_usdt()
            except Exception:
                pass
            try:
                positions = self.broker.linear_positions()
            except Exception:
                log.exception("em6 bybit view positions")
        closed: list[dict] = []
        if self.broker.configured():
            closed = self._closed_rows_from_exchange(limit=200)
        if not closed and self._conn is not None:
            closed = self.store.list_trades(self._conn, "closed", 200)
        open_rows: list[dict[str, Any]] = []
        if positions:
            open_rows = self._open_rows_from_exchange(positions)
        elif self.open_trades:
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
                        "ema60": live.ema60,
                        "grid_levels": live.grid_levels,
                        "trail_roe_pct": em6_bybit_active_trail_roe_pct(
                            self._max_roe(live)
                        ),
                        "notional_usd": round(live.qty * live.entry_price, 2),
                        "source": "local",
                    }
                )
        unrealized_total = sum(float(r.get("unrealised_pnl") or 0) for r in open_rows)
        wins = sum(1 for r in closed if float(r.get("pnl_usd") or 0) > 0)
        n_closed = len(closed)
        sum_pnl = sum(float(r.get("pnl_usd") or 0) for r in closed)
        cand_rows = []
        by_column: dict[str, list[dict]] = {}
        for w in sorted(self._watch.values(), key=lambda x: x.last_stretch, reverse=True):
            v = w.to_view()
            col = stretch_column_label(w.last_stretch)
            v["stretch_column"] = col
            cand_rows.append(v)
            by_column.setdefault(col, []).append(v)
        columns = [
            {"label": label, "candidates": by_column[label]}
            for label in sorted(by_column.keys(), key=lambda s: float(s.split("–")[0]), reverse=True)
        ]
        return {
            "summary": {
                "label": "EMA6 Bybit Demo",
                "wallet_equity": round(wallet.get("equity", 0), 2),
                "wallet_available": round(wallet.get("available", 0), 2),
                "margin_usd": config.em6_bybit_margin_usd(),
                "leverage": config.em6_bybit_leverage(),
                "notional_usd": round(
                    config.em6_bybit_margin_usd() * config.em6_bybit_leverage(), 2
                ),
                "open_trades": len(open_rows),
                "closed_trades": n_closed,
                "win_rate": round(100.0 * wins / n_closed, 1) if n_closed else 0.0,
                "total_pnl_closed": round(sum_pnl, 2),
                "total_unrealised_pnl": round(unrealized_total, 2),
                "watch_count": len(cand_rows),
                "stretch_floor_pct": config.EM6_BYBIT_STRETCH_FLOOR_PCT,
                "data_source": "bybit" if self.broker.configured() else "local",
            },
            "candidates": cand_rows,
            "candidate_columns": columns,
            "open_trades": open_rows,
            "closed_trades": closed,
        }
