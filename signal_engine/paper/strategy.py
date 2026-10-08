"""Тест стратегии: сам ищет пампы, ждёт затухания, открывает и ведёт виртуальные шорты.

Кандидат — один памп одной монеты. Пока он жив, каждые 3 секунды проверяются
все обязательные условия. Варианты входа идут параллельно, у каждого свой счёт:
«5 из 9», «все 9» и «сильная двойная вершина + 3 условия». Не хватило ровно
одного из 9 — запускается теневая сделка: что было бы при входе.
Всё пишется в SQLite для анализа.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

import config
from signal_engine.flow import oi_change_pct
from signal_engine.paper.analytics import compute_analytics
from signal_engine.paper.detect import (
    CHECK_LABELS,
    MANDATORY,
    VARIANT_LABELS,
    PumpInfo,
    btc_change_4h,
    evaluate,
    find_pump,
    grade_for,
)
from signal_engine.paper.position import Position
from signal_engine.paper.store import PaperStore
from signal_engine.paper.tape import TapeBook, minute_start
from signal_engine.state import Bar, SymbolState

log = logging.getLogger(__name__)

BOARD_TYPE = "paper_test"
VARIANTS = config.PAPER_VARIANTS
_SHADOW_MARGIN = config.PAPER_START_BALANCE_USD * config.PAPER_MARGIN_PCT / 100.0
_REASON_CONDITIONS = "условия пампа больше не выполняются"
_MINUTES_KEEP_MS = 180 * 60_000


@dataclass
class OpenTrade:
    id: int
    variant: str
    symbol: str
    kind: str
    pos: Position
    score: float
    grade: str
    strict_btc: bool
    entry: dict
    candidate_id: int | None
    last_check: int


@dataclass
class Candidate:
    id: int
    symbol: str
    pump: PumpInfo
    started_at: int
    scans: int = 0
    fail_counts: dict[str, int] = field(default_factory=dict)
    best_passed: int = 0
    last_eval: dict | None = None
    near_miss: bool = False
    entered: list[str] = field(default_factory=list)
    last_trade_id: int | None = None
    note: str | None = None
    dirty: bool = True


@dataclass
class Shadow:
    candidate_id: int
    symbol: str
    missing: str
    pos: Position
    last_check: int


class PaperStrategy:
    def __init__(self, store: PaperStore | None = None) -> None:
        self.store = store or PaperStore(config.PAPER_SQLITE_PATH)
        self.tape = TapeBook()
        self.klines: dict[str, dict[str, list[Bar]]] = {}
        self.kline_at: dict[str, float] = {}
        self.balances: dict[str, float] = {v: config.PAPER_START_BALANCE_USD for v in VARIANTS}
        self.trades: dict[tuple[str, str], OpenTrade] = {}
        self.candidates: dict[str, Candidate] = {}
        self.shadows: dict[int, Shadow] = {}
        self.last_close: dict[tuple[str, str], int] = {}
        self.expired_peaks: dict[str, int] = {}
        self.started_ms = int(time.time() * 1000)
        self._next_detect = 0
        self._next_persist = 0
        self._next_equity = 0
        self._next_tape = 0
        self._next_analytics = 0
        self._analytics: dict = {}
        self._opened = False

    # --- жизненный цикл ---

    def open(self) -> None:
        self.store.open()
        now = int(time.time() * 1000)
        self.started_ms = now
        if self.store.get_kv("started_at") is None:
            self.store.set_kv("started_at", str(now))
        for variant in VARIANTS:
            saved = self.store.get_kv(f"balance:{variant}")
            self.balances[variant] = float(saved) if saved is not None else config.PAPER_START_BALANCE_USD
            if saved is None:
                self.store.set_kv(f"balance:{variant}", str(self.balances[variant]))
        if self.store.get_kv("revived_restart_expiry") is None:
            # До защиты от перезапуска кандидаты снимались, пока свечи ещё не подгрузились.
            since = now - config.PAPER_LONG_LIFETIME_HOURS * 3_600_000
            revived = self.store.revive_candidates(_REASON_CONDITIONS, since)
            self.store.set_kv("revived_restart_expiry", str(now))
            if revived:
                log.info("Тест: возвращено кандидатов после ошибочного снятия: %s", revived)
        for row in self.store.open_trades():
            pos = Position(
                symbol=row["symbol"],
                opened_at=int(row["opened_at"]),
                entry_price=float(row["entry_price"]),
                margin=float(row["margin"]),
                leverage=int(row["leverage"]),
                best_price=float(row["best_price"]),
                worst_price=float(row["worst_price"]),
                stop_price=float(row["stop_price"]),
                liq_price=float(row["liq_price"]),
                entry_fee=float(row["entry_fee"]),
                funding_paid=float(row["funding_paid"] or 0),
                next_funding_ts=row["next_funding_ts"],
                last_price=float(row["last_price"] or row["entry_price"]),
            )
            variant = str(row["variant"] or "v9")
            self.trades[(variant, row["symbol"])] = OpenTrade(
                id=int(row["id"]),
                variant=variant,
                symbol=row["symbol"],
                kind=str(row["kind"] or ""),
                pos=pos,
                score=float(row["score"] or 0),
                grade=str(row["grade"] or "C"),
                strict_btc=bool(row["strict_btc"]),
                entry=_loads(row["entry_json"]),
                candidate_id=row["candidate_id"],
                last_check=now,
            )
        active = sorted(self.store.active_candidates(), key=lambda r: (int(r["peak_ts"] or 0), int(r["id"])))
        for row in active:
            older = self.candidates.get(row["symbol"])
            if older is not None:
                self._end_candidate(older, "дубль после перезапуска", now)
            pump = _pump_from_row(row)
            last_eval = _loads(row["last_eval"]) or None
            self.candidates[row["symbol"]] = Candidate(
                id=int(row["id"]),
                symbol=row["symbol"],
                pump=pump,
                started_at=int(row["started_at"]),
                scans=int(row["scans"] or 0),
                fail_counts=_loads(row["fail_counts"]) or {},
                best_passed=int(row["best_passed"] or 0),
                last_eval=last_eval,
                near_miss=row["near_miss_at"] is not None,
                entered=_loads_list(row["variants"]),
                last_trade_id=row["trade_id"],
                dirty=False,
            )
        for row in self.store.open_shadows():
            pos = Position(
                symbol=row["symbol"],
                opened_at=int(row["shadow_opened_at"]),
                entry_price=float(row["shadow_entry_price"]),
                margin=float(row["shadow_margin"] or _SHADOW_MARGIN),
                best_price=float(row["shadow_best"]),
                worst_price=float(row["shadow_worst"] or row["shadow_entry_price"]),
                stop_price=float(row["shadow_stop"]),
                liq_price=float(row["shadow_liq"]),
                entry_fee=float(row["shadow_entry_fee"]),
            )
            self.shadows[int(row["id"])] = Shadow(
                candidate_id=int(row["id"]),
                symbol=row["symbol"],
                missing=str(row["near_miss_missing"] or ""),
                pos=pos,
                last_check=now,
            )
        self.last_close = self.store.last_close_by_symbol()
        for row in self.store.db.execute(
            "SELECT symbol, MAX(peak_ts) AS ts FROM paper_candidates WHERE status != 'watching' GROUP BY symbol"
        ):
            if row["ts"] is not None:
                self.expired_peaks[str(row["symbol"])] = int(row["ts"])
        self._load_tape(now)
        self._analytics = compute_analytics(self.store.db, self.balances)
        self._opened = True
        log.info(
            "Тест стратегии: балансы %s, открытых %s, кандидатов %s, теневых %s",
            ", ".join(f"{v} {self.balances[v]:.2f}" for v in VARIANTS),
            len(self.trades),
            len(self.candidates),
            len(self.shadows),
        )

    def close(self) -> None:
        if self._opened:
            now = int(time.time() * 1000)
            self._persist(now, force=True)
            self._save_tape(now)
        self.store.close()

    # --- входящие данные ---

    def ingest(self, message: dict) -> None:
        self.tape.ingest(message)

    def kline_wanted(self) -> list[str]:
        return sorted(set(self.candidates))

    def on_klines(self, symbol: str, interval: str, candles: list[dict]) -> None:
        bars = []
        for row in candles:
            try:
                bars.append(
                    Bar(
                        int(row["timestamp"]),
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                        float(row["volume"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if bars:
            self.klines.setdefault(symbol, {})[interval] = bars
            self.kline_at[symbol] = time.time()

    # --- скан ---

    def scan(self, states: dict[str, SymbolState], now_ms: int) -> dict:
        btc_4h = btc_change_4h(states.get(config.PAPER_BTC_SYMBOL), now_ms)
        self._update_trades(states, now_ms)
        self._update_shadows(states, now_ms)
        if now_ms >= self._next_detect:
            self._detect(states, now_ms)
            self._next_detect = now_ms + config.PAPER_DETECT_INTERVAL_SEC * 1000
        self._evaluate(states, btc_4h, now_ms)
        self._persist(now_ms)
        if now_ms >= self._next_equity:
            for variant in VARIANTS:
                self._snapshot_equity(variant, now_ms)
            self._next_equity = now_ms + config.PAPER_EQUITY_SNAPSHOT_SEC * 1000
        if now_ms >= self._next_tape:
            self._save_tape(now_ms)
            self._next_tape = now_ms + 300_000
        if now_ms >= self._next_analytics:
            self._analytics = compute_analytics(self.store.db, self.balances)
            self._next_analytics = now_ms + 30_000
        return {"type": BOARD_TYPE, "timestamp": now_ms, "data": self.view(now_ms, btc_4h)}

    def _variant_trades(self, variant: str) -> list[OpenTrade]:
        return [t for t in self.trades.values() if t.variant == variant]

    def used_margin(self, variant: str) -> float:
        return sum(t.pos.margin for t in self._variant_trades(variant))

    def unrealized(self, variant: str) -> float:
        return sum(t.pos.net_pnl(t.pos.last_price) for t in self._variant_trades(variant))

    def equity(self, variant: str) -> float:
        return self.balances[variant] + self.unrealized(variant)

    def _snapshot_equity(self, variant: str, now_ms: int) -> None:
        self.store.add_equity(
            variant, now_ms, self.balances[variant], self.equity(variant), len(self._variant_trades(variant))
        )

    def _update_trades(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for trade in list(self.trades.values()):
            state = states.get(trade.symbol)
            if state is None or not state.last_price:
                continue
            pos = trade.pos
            low, high, last = _price_range(state, trade.last_check)
            trade.last_check = now_ms
            self._funding(pos, trade.symbol, state, now_ms)
            reason = pos.update(low, high, last)
            if reason:
                self._close_trade(trade, reason, state, now_ms)

    def _funding(self, pos: Position, symbol: str, state: SymbolState, now_ms: int) -> None:
        tape = self.tape.symbols.get(symbol)
        if pos.next_funding_ts is None and tape is not None and tape.next_funding_ts:
            if tape.next_funding_ts > now_ms:
                pos.next_funding_ts = tape.next_funding_ts
        if pos.next_funding_ts is not None and now_ms >= pos.next_funding_ts:
            paid = pos.apply_funding(now_ms, state.funding_rate, float(state.last_price or pos.last_price))
            if paid:
                log.info("Funding %s: %+.4f USD", symbol, paid)

    def _close_trade(self, trade: OpenTrade, reason: str, state: SymbolState, now_ms: int) -> None:
        pos = trade.pos
        variant = trade.variant
        result = pos.close_result(reason)
        self.balances[variant] += result["pnl_usd"]
        points = state.oi_points()
        exit_json = {
            "duration_min": round((now_ms - pos.opened_at) / 60_000),
            "last_price": pos.last_price,
            "best_price": pos.best_price,
            "worst_price": pos.worst_price,
            "funding_paid": pos.funding_paid,
            "oi_1h_pct": _r(oi_change_pct(points, 60)) if len(points) >= 2 else None,
            "funding_rate": state.funding_rate,
        }
        self.store.update_trade(
            trade.id,
            {
                "status": "closed",
                "closed_at": now_ms,
                "exit_price": result["exit_price"],
                "exit_reason": reason,
                "exit_fee": result["exit_fee"],
                "pnl_usd": result["pnl_usd"],
                "roe_pct": result["roe_pct"],
                "max_roe": pos.max_roe(),
                "min_roe": pos.min_roe(),
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "stop_price": pos.stop_price,
                "last_price": pos.last_price,
                "funding_paid": pos.funding_paid,
                "balance_after": self.balances[variant],
                "exit_json": exit_json,
            },
            commit=False,
        )
        self.trades.pop((variant, trade.symbol), None)
        self.store.set_kv(f"balance:{variant}", str(self.balances[variant]))
        self._snapshot_equity(variant, now_ms)
        self.last_close[(variant, trade.symbol)] = now_ms
        self._next_analytics = 0
        log.info(
            "Тест [%s]: закрыт шорт %s (%s), P&L %+.2f USD (%+.1f%%), баланс %.2f",
            variant,
            trade.symbol,
            reason,
            result["pnl_usd"],
            result["roe_pct"],
            self.balances[variant],
        )

    def _update_shadows(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for cid, shadow in list(self.shadows.items()):
            state = states.get(shadow.symbol)
            if state is None or not state.last_price:
                continue
            low, high, last = _price_range(state, shadow.last_check)
            shadow.last_check = now_ms
            reason = shadow.pos.update(low, high, last)
            if reason:
                result = shadow.pos.close_result(reason)
                self.store.update_candidate(
                    cid,
                    {
                        "shadow_status": "closed",
                        "shadow_closed_at": now_ms,
                        "shadow_exit_price": result["exit_price"],
                        "shadow_exit_reason": reason,
                        "shadow_pnl_usd": result["pnl_usd"],
                        "shadow_roe": result["roe_pct"],
                        "shadow_max_roe": shadow.pos.max_roe(),
                        "shadow_best": shadow.pos.best_price,
                        "shadow_worst": shadow.pos.worst_price,
                        "shadow_stop": shadow.pos.stop_price,
                    },
                )
                self.shadows.pop(cid, None)
                self._next_analytics = 0

    def _detect(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for symbol, state in states.items():
            if symbol in self.candidates or not state.last_price:
                continue
            pump = find_pump(state, self.tape.symbols.get(symbol), now_ms)
            if pump is None:
                continue
            if self.expired_peaks.get(symbol) == pump.peak_ts:
                continue
            cid = self.store.insert_candidate(
                {
                    "symbol": symbol,
                    "kind": pump.kind,
                    "status": "watching",
                    "started_at": now_ms,
                    "updated_at": now_ms,
                    **_pump_fields(pump),
                    "fail_counts": {},
                }
            )
            self.candidates[symbol] = Candidate(id=cid, symbol=symbol, pump=pump, started_at=now_ms)
            log.info(
                "Тест: кандидат %s — %s памп +%.1f%% (%s)",
                symbol,
                pump.kind,
                pump.growth_pct,
                pump.trigger,
            )

    def _ready(self, state: SymbolState, cand: Candidate, now_ms: int) -> bool:
        """Хватает ли истории в памяти, чтобы честно решить, что памп кончился."""
        if now_ms - self.started_ms < config.PAPER_STARTUP_GRACE_MIN * 60_000:
            return False
        if len(state.bars_htf.get("15") or []) < config.PAPER_READY_15M_BARS:
            return False
        if cand.pump.kind == "long" and len(state.bars_htf.get("240") or []) < config.PAPER_READY_4H_BARS:
            return False
        return True

    def _evaluate(self, states: dict[str, SymbolState], btc_4h: float | None, now_ms: int) -> None:
        cooldown = config.PAPER_REENTRY_COOLDOWN_SEC * 1000
        for symbol, cand in list(self.candidates.items()):
            state = states.get(symbol)
            if state is None or not state.last_price:
                continue
            tape = self.tape.get(symbol)
            pump = find_pump(state, tape, now_ms)
            if pump is None:
                reason = _expire_reason(cand.pump, state, now_ms)
                if reason == _REASON_CONDITIONS and not self._ready(state, cand, now_ms):
                    continue
                self._end_candidate(cand, reason, now_ms)
                continue
            cand.pump = pump
            ev = evaluate(state, tape, pump, self.klines.get(symbol, {}), btc_4h, now_ms)
            cand.scans += 1
            for key in ev.failed:
                cand.fail_counts[key] = cand.fail_counts.get(key, 0) + 1
            cand.best_passed = max(cand.best_passed, ev.passed_count)
            cand.last_eval = ev.to_data()
            cand.dirty = True
            notes = []
            for variant in ev.variants:
                if (variant, symbol) in self.trades:
                    continue
                if now_ms - self.last_close.get((variant, symbol), 0) < cooldown:
                    continue
                balance = self.balances[variant]
                margin = balance * config.PAPER_MARGIN_PCT / 100.0
                if margin <= 0 or balance - self.used_margin(variant) < margin:
                    notes.append(f"{VARIANT_LABELS[variant]}: нет свободной маржи")
                    continue
                self._open_trade(variant, cand, state, ev, margin, now_ms)
            cand.note = "; ".join(notes) or None
            if len(ev.failed) == 1 and not cand.near_miss:
                self._start_shadow(cand, state, ev.failed[0], now_ms)

    def _open_trade(self, variant: str, cand: Candidate, state: SymbolState, ev, margin: float, now_ms: int) -> None:
        price = float(state.last_price)
        tape = self.tape.symbols.get(cand.symbol)
        nft = tape.next_funding_ts if tape is not None and tape.next_funding_ts and tape.next_funding_ts > now_ms else None
        pos = Position(symbol=cand.symbol, opened_at=now_ms, entry_price=price, margin=margin, next_funding_ts=nft)
        entry = ev.to_data()
        trade_id = self.store.insert_trade(
            {
                "symbol": cand.symbol,
                "variant": variant,
                "candidate_id": cand.id,
                "kind": cand.pump.kind,
                "status": "open",
                "opened_at": now_ms,
                "entry_price": price,
                "margin": margin,
                "leverage": pos.leverage,
                "notional": pos.notional,
                "qty": pos.qty,
                "liq_price": pos.liq_price,
                "stop_price": pos.stop_price,
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "last_price": price,
                "entry_fee": pos.entry_fee,
                "funding_paid": 0.0,
                "next_funding_ts": nft,
                "score": ev.score,
                "grade": grade_for(ev.score),
                "strict_btc": ev.strict_btc,
                "balance_before": self.balances[variant],
                "entry_json": entry,
            }
        )
        self.trades[(variant, cand.symbol)] = OpenTrade(
            id=trade_id,
            variant=variant,
            symbol=cand.symbol,
            kind=cand.pump.kind,
            pos=pos,
            score=ev.score,
            grade=grade_for(ev.score),
            strict_btc=ev.strict_btc,
            entry=entry,
            candidate_id=cand.id,
            last_check=now_ms,
        )
        if variant not in cand.entered:
            cand.entered.append(variant)
        cand.last_trade_id = trade_id
        cand.dirty = True
        self._next_analytics = 0
        log.info(
            "Тест [%s]: открыт шорт %s по %s, маржа %.2f USD, условий %s/%s, балл %.1f",
            variant,
            cand.symbol,
            price,
            margin,
            ev.passed_count,
            len(MANDATORY),
            ev.score,
        )

    def _start_shadow(self, cand: Candidate, state: SymbolState, missing: str, now_ms: int) -> None:
        price = float(state.last_price)
        pos = Position(symbol=cand.symbol, opened_at=now_ms, entry_price=price, margin=_SHADOW_MARGIN)
        cand.near_miss = True
        self.store.update_candidate(
            cand.id,
            {
                "near_miss_at": now_ms,
                "near_miss_missing": missing,
                "near_miss_json": cand.last_eval,
                "shadow_status": "open",
                "shadow_entry_price": price,
                "shadow_opened_at": now_ms,
                "shadow_stop": pos.stop_price,
                "shadow_best": pos.best_price,
                "shadow_worst": pos.worst_price,
                "shadow_liq": pos.liq_price,
                "shadow_entry_fee": pos.entry_fee,
                "shadow_margin": pos.margin,
            },
        )
        self.shadows[cand.id] = Shadow(cand.id, cand.symbol, missing, pos, now_ms)

    def _end_candidate(self, cand: Candidate, reason: str, now_ms: int) -> None:
        status = "entered" if cand.entered else "expired"
        fields = {
            "status": status,
            "ended_at": now_ms,
            "end_reason": reason,
            "updated_at": now_ms,
            "scans": cand.scans,
            "fail_counts": cand.fail_counts,
            "best_passed": cand.best_passed,
            "last_eval": cand.last_eval or {},
            "variants": cand.entered,
            "trade_id": cand.last_trade_id,
            **_pump_fields(cand.pump),
        }
        self.store.update_candidate(cand.id, fields)
        self.expired_peaks[cand.symbol] = cand.pump.peak_ts
        self.candidates.pop(cand.symbol, None)

    def _persist(self, now_ms: int, force: bool = False) -> None:
        if not force and now_ms < self._next_persist:
            return
        self._next_persist = now_ms + config.PAPER_PERSIST_INTERVAL_SEC * 1000
        for trade in self.trades.values():
            pos = trade.pos
            self.store.update_trade(
                trade.id,
                {
                    "stop_price": pos.stop_price,
                    "best_price": pos.best_price,
                    "worst_price": pos.worst_price,
                    "last_price": pos.last_price,
                    "funding_paid": pos.funding_paid,
                    "next_funding_ts": pos.next_funding_ts,
                    "max_roe": pos.max_roe(),
                    "min_roe": pos.min_roe(),
                },
                commit=False,
            )
        for cand in self.candidates.values():
            if not cand.dirty:
                continue
            self.store.update_candidate(
                cand.id,
                {
                    "updated_at": now_ms,
                    "scans": cand.scans,
                    "fail_counts": cand.fail_counts,
                    "best_passed": cand.best_passed,
                    "last_eval": cand.last_eval or {},
                    "variants": cand.entered,
                    "trade_id": cand.last_trade_id,
                    **_pump_fields(cand.pump),
                },
                commit=False,
            )
            cand.dirty = False
        for shadow in self.shadows.values():
            self.store.update_candidate(
                shadow.candidate_id,
                {
                    "shadow_stop": shadow.pos.stop_price,
                    "shadow_best": shadow.pos.best_price,
                    "shadow_worst": shadow.pos.worst_price,
                    "shadow_max_roe": shadow.pos.max_roe(),
                },
                commit=False,
            )
        self.store.commit()

    def _save_tape(self, now_ms: int) -> None:
        since = now_ms - 15 * 60_000
        rows: list[tuple[str, int, float, float]] = []
        minute_rows: list[tuple[str, int, float, float, float, float]] = []
        for symbol, tape in self.tape.symbols.items():
            for ts, (buy, sell) in tape.buckets.items():
                if ts >= since:
                    rows.append((symbol, ts, buy, sell))
            keys = {k for k in tape.minutes if k >= since}
            keys |= {k for k in tape.liq_long if k >= since}
            keys |= {k for k in tape.liq_short if k >= since}
            for ts in keys:
                buy, sell = tape.minutes.get(ts) or (0.0, 0.0)
                minute_rows.append(
                    (symbol, ts, buy, sell, tape.liq_long.get(ts, 0.0), tape.liq_short.get(ts, 0.0))
                )
        self.store.save_tape(rows, now_ms - config.PAPER_TAPE_RETENTION_HOURS * 3_600_000)
        self.store.save_tape_minutes(minute_rows, now_ms - _MINUTES_KEEP_MS)

    def _load_tape(self, now_ms: int) -> None:
        cutoff = now_ms - config.PAPER_TAPE_RETENTION_HOURS * 3_600_000
        for row in self.store.load_tape(cutoff):
            tape = self.tape.get(str(row["symbol"]))
            ts = int(row["ts"])
            tape.buckets[ts] = [float(row["buy"]), float(row["sell"])]
            if tape.first_ts is None or ts < tape.first_ts:
                tape.first_ts = ts
        for row in self.store.load_tape_minutes(now_ms - _MINUTES_KEEP_MS):
            tape = self.tape.get(str(row["symbol"]))
            ts = int(row["ts"])
            if row["buy"] or row["sell"]:
                tape.minutes[ts] = [float(row["buy"]), float(row["sell"])]
            if row["liq_long"]:
                tape.liq_long[ts] = float(row["liq_long"])
            if row["liq_short"]:
                tape.liq_short[ts] = float(row["liq_short"])

    # --- вид для браузера ---

    def view(self, now_ms: int, btc_4h: float | None) -> dict:
        trades = sorted(self.trades.values(), key=lambda t: t.pos.opened_at, reverse=True)
        cands = sorted(
            self.candidates.values(),
            key=lambda c: (-((c.last_eval or {}).get("passed_count") or 0), -c.pump.growth_pct),
        )
        accounts = {}
        for variant in VARIANTS:
            used = self.used_margin(variant)
            unreal = self.unrealized(variant)
            balance = self.balances[variant]
            accounts[variant] = {
                "label": VARIANT_LABELS[variant],
                "balance": round(balance, 2),
                "equity": round(balance + unreal, 2),
                "unrealized": round(unreal, 2),
                "used_margin": round(used, 2),
                "free_margin": round(balance - used, 2),
                "open_trades": len(self._variant_trades(variant)),
            }
        return {
            "updated_at": now_ms,
            "summary": {
                "start_balance": config.PAPER_START_BALANCE_USD,
                "accounts": accounts,
                "candidates": len(self.candidates),
                "shadows_open": len(self.shadows),
                "btc_4h_pct": _r(btc_4h),
                "btc_strict": btc_4h is not None and btc_4h >= config.PAPER_BTC_STRICT_4H_PCT,
                "margin_pct": config.PAPER_MARGIN_PCT,
                "leverage": config.PAPER_LEVERAGE,
            },
            "variants": list(VARIANTS),
            "variant_labels": VARIANT_LABELS,
            "open_trades": [self._trade_view(t, now_ms) for t in trades],
            "candidates": [self._candidate_view(c, now_ms) for c in cands],
            "check_labels": CHECK_LABELS,
            "mandatory": list(MANDATORY),
            "analytics": self._analytics,
        }

    def _trade_view(self, trade: OpenTrade, now_ms: int) -> dict:
        pos = trade.pos
        price = pos.last_price
        pump = (trade.entry.get("metrics") or {}).get("pump") or {}
        return {
            "id": trade.id,
            "variant": trade.variant,
            "symbol": trade.symbol,
            "kind": trade.kind,
            "pump": pump,
            "opened_at": pos.opened_at,
            "duration_min": round((now_ms - pos.opened_at) / 60_000),
            "entry_price": pos.entry_price,
            "last_price": price,
            "stop_price": pos.stop_price,
            "liq_price": pos.liq_price,
            "best_price": pos.best_price,
            "margin": round(pos.margin, 2),
            "notional": round(pos.notional, 2),
            "qty": pos.qty,
            "price_change_pct": _r((price / pos.entry_price - 1) * 100.0),
            "roe_pct": _r(pos.net_roe(price)),
            "pnl_usd": _r(pos.net_pnl(price)),
            "max_roe": _r(pos.max_roe()),
            "min_roe": _r(pos.min_roe()),
            "entry_fee": _r(pos.entry_fee, 4),
            "funding_paid": _r(pos.funding_paid, 4),
            "next_funding_ts": pos.next_funding_ts,
            "score": _r(trade.score, 1),
            "grade": trade.grade,
            "strict_btc": trade.strict_btc,
            "entry": trade.entry,
        }

    def _candidate_view(self, cand: Candidate, now_ms: int) -> dict:
        shadow = self.shadows.get(cand.id)
        return {
            "id": cand.id,
            "symbol": cand.symbol,
            "pump": cand.pump.to_data(),
            "started_at": cand.started_at,
            "watch_min": round((now_ms - cand.started_at) / 60_000),
            "scans": cand.scans,
            "best_passed": cand.best_passed,
            "entered": cand.entered,
            "open_in": [v for v in VARIANTS if (v, cand.symbol) in self.trades],
            "note": cand.note,
            "eval": cand.last_eval,
            "shadow": (
                {
                    "entry_price": shadow.pos.entry_price,
                    "roe_pct": _r(shadow.pos.net_roe(shadow.pos.last_price)),
                    "missing": shadow.missing,
                }
                if shadow
                else None
            ),
        }


def _price_range(state: SymbolState, since_ms: int) -> tuple[float, float, float]:
    last = float(state.last_price or 0)
    low = high = last
    start = minute_start(since_ms)
    for bar in state.bars_1m:
        if bar.timestamp > start:
            low = min(low, bar.low)
            high = max(high, bar.high)
    return low, high, last


def _expire_reason(pump: PumpInfo, state: SymbolState, now_ms: int) -> str:
    last = float(state.last_price or 0)
    if pump.peak_price > 0 and last > 0:
        if (1 - last / pump.peak_price) * 100.0 > config.PAPER_MAX_DRAWDOWN_FROM_PEAK_PCT:
            return "откат от пика"
    hours = config.PAPER_SHORT_LIFETIME_HOURS if pump.kind == "short" else config.PAPER_LONG_LIFETIME_HOURS
    if now_ms - pump.peak_ts > hours * 3_600_000:
        return "истекло время после пика"
    return _REASON_CONDITIONS


def _pump_fields(pump: PumpInfo) -> dict:
    return {
        "kind": pump.kind,
        "peak_price": pump.peak_price,
        "peak_ts": pump.peak_ts,
        "valley_price": pump.valley_price,
        "valley_ts": pump.valley_ts,
        "growth_pct": pump.growth_pct,
    }


def _pump_from_row(row) -> PumpInfo:
    last_eval = _loads(row["last_eval"]) or {}
    data = (last_eval.get("metrics") or {}).get("pump") or {}
    return PumpInfo(
        kind=str(row["kind"] or "short"),
        trigger=str(data.get("trigger") or ""),
        growth_pct=float(row["growth_pct"] or 0),
        valley_price=float(row["valley_price"] or 0),
        valley_ts=int(row["valley_ts"] or 0),
        peak_price=float(row["peak_price"] or 0),
        peak_ts=int(row["peak_ts"] or 0),
        growth=data.get("growth") or {},
        volume_ratio=data.get("volume_ratio"),
        volume_avg_ratio=data.get("volume_avg_ratio"),
        buy_share_pct=data.get("buy_share_pct"),
        tape_minutes=int(data.get("tape_minutes") or 0),
    )


def _loads(raw) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _loads_list(raw) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def _r(value, digits: int = 2):
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None
