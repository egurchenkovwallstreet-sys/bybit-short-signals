"""Скан раз в 3 секунды: новые сигналы, обновление галочек, исход.

Памп, из-за которого карточка появилась, не снимается. Остальные
галочки живые: колонка переезжает вместе с ними.
"""

from __future__ import annotations

import logging

import config
from signal_engine.evaluate import Reading, evaluate
from signal_engine.flow import funding_extreme
from signal_engine.models import Signal
from signal_engine.outcomes import classify_outcome, short_pnl_pct
from signal_engine.rating import column_for, probability_pct, signal_rating
from signal_engine.state import SymbolState
from signal_engine.pump_scan import build_pump_scan_board
from signal_engine.x2_retrace import build_x2_retrace_board
from signal_engine.pump_strategy import build_pump_strategy_board
from signal_engine.paper.strategy import PaperStrategy
from signal_engine.store import SignalStore
from signal_engine.watch_store import WatchStore


log = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        store: SignalStore,
        watches: WatchStore | None = None,
        paper: PaperStrategy | None = None,
    ) -> None:
        self.store = store
        self.watches = watches or WatchStore(config.SQLITE_PATH)
        self.paper = paper
        self.symbols: dict[str, SymbolState] = {}
        self.open_signals: dict[str, Signal] = {}
        self._signal_column_pending: dict[str, tuple[int, int]] = {}

    def restore(self) -> None:
        self.watches.open()
        if self.paper is not None:
            self.paper.open()
        for signal in self.store.load_open():
            self.open_signals[signal.symbol] = signal
            self.symbols.setdefault(signal.symbol, SymbolState(signal.symbol))

    def ingest(self, message: dict) -> None:
        symbol = message.get("symbol")
        if not symbol or not isinstance(message, dict):
            return
        state = self.symbols.get(symbol)
        if state is None:
            state = SymbolState(symbol)
            self.symbols[symbol] = state
        try:
            state.ingest(message)
        except (TypeError, ValueError):
            log.exception("Сообщение %s %s пропущено", symbol, message.get("type"))
        if self.paper is not None:
            self.paper.ingest(message)

    def scan(self, now_ms: int) -> list[dict]:
        wins, total = self.store.outcome_counts()
        changed: list[dict] = []
        names = set(self.symbols) | set(self.open_signals)
        for symbol in sorted(names):
            state = self.symbols.setdefault(symbol, SymbolState(symbol))
            signal = self.open_signals.get(symbol)
            if signal is None:
                if not _meets_turnover(state):
                    continue
                opened = self._try_open(state, now_ms, wins, total)
                if opened is not None:
                    changed.append(opened.to_message("open", now_ms))
                continue
            if not _meets_turnover(state):
                self._close(signal, "LOW_VOLUME", state.last_price or signal.last_price, now_ms)
                changed.append(signal.to_message("close", now_ms))
                continue
            outcome = classify_outcome(signal.entry_price, state.last_price or signal.last_price, signal.created_at, now_ms)
            if outcome is not None:
                self._close(signal, outcome, state.last_price or signal.last_price, now_ms)
                changed.append(signal.to_message("close", now_ms))
                continue
            if self._refresh(signal, evaluate(state, now_ms), now_ms, wins, total):
                changed.append(signal.to_message("update", now_ms))
        # Доска каждые 3 секунды — снимок колонок, даже если галочки не менялись.
        out = [
            *changed,
            self._board(now_ms),
            build_pump_scan_board(self.symbols, now_ms, self.watches),
            build_x2_retrace_board(self.symbols, now_ms, self.watches),
            build_pump_strategy_board(self.symbols, now_ms, self.watches),
        ]
        if self.paper is not None:
            try:
                out.append(self.paper.scan(self.symbols, now_ms))
            except Exception:
                log.exception("Тест стратегии: ошибка скана")
        return out

    def _try_open(self, state: SymbolState, now_ms: int, wins: int, total: int) -> Signal | None:
        if state.last_price is None or state.last_price <= 0:
            return None
        reading = evaluate(state, now_ms)
        if not reading.pump:
            return None
        signal = Signal(
            symbol=state.symbol,
            created_at=now_ms,
            updated_at=now_ms,
            entry_price=state.last_price,
            last_price=state.last_price,
            strength=1,
            rating=0,
            probability=0,
            quality=0,
            tf_match=0,
            extra=0,
            color="gray",
            status="НАБЛЮДЕНИЕ",
            label="1/5",
        )
        self._apply(signal, reading, now_ms, wins, total, pump_latched=True)
        self.store.insert(signal)
        self.open_signals[signal.symbol] = signal
        log.info(
            "Сигнал %s %s, рейтинг %.1f, вход %s",
            signal.symbol,
            signal.label,
            signal.rating,
            signal.entry_price,
        )
        return signal

    def _refresh(self, signal: Signal, reading: Reading, now_ms: int, wins: int, total: int) -> bool:
        before = _signature(signal)
        price = self.symbols[signal.symbol].last_price or signal.last_price
        signal.last_price = price
        signal.pnl_pct = short_pnl_pct(signal.entry_price, price)
        self._apply(signal, reading, now_ms, wins, total, pump_latched=True)
        if _signature(signal) == before:
            return False
        self.store.update(signal)
        return True

    def _close(self, signal: Signal, outcome: str, price: float, now_ms: int) -> None:
        signal.outcome = outcome
        signal.exit_price = price
        signal.exit_at = now_ms
        signal.last_price = price
        signal.updated_at = now_ms
        signal.pnl_pct = short_pnl_pct(signal.entry_price, price)
        self.store.update(signal)
        self.open_signals.pop(signal.symbol, None)
        log.info("Исход %s %s, P&L %s", signal.symbol, outcome, signal.pnl_pct)

    def _apply(
        self,
        signal: Signal,
        reading: Reading,
        now_ms: int,
        wins: int,
        total: int,
        pump_latched: bool,
    ) -> None:
        strength = reading.strength(pump_latched)
        extra = reading.extra_count()
        candidate_level = min(5, max(1, strength))
        confirmed_level = self._confirmed_signal_strength(signal.symbol, candidate_level, now_ms)
        strength = confirmed_level
        probability = probability_pct(
            sweep=reading.sweep,
            liquidations_faded=reading.liquidations_faded,
            oi_drop=reading.oi_drop,
            cvd_divergence=reading.cvd_divergence,
            round_level=reading.round_level,
            funding_extreme=funding_extreme(reading.funding_rate),
            history_wins=wins,
            history_total=total,
        )
        column = column_for(strength)
        signal.updated_at = now_ms
        signal.strength = int(column["strength"])
        signal.color = str(column["color"])
        signal.status = str(column["status"])
        signal.label = str(column["label"])
        signal.rating = signal_rating(signal.strength, probability, reading.quality, reading.tf_match, extra)
        signal.probability = probability
        signal.quality = reading.quality
        signal.tf_match = reading.tf_match
        signal.extra = extra
        signal.price_change_5m = reading.price_change_5m
        signal.price_change_15m = reading.price_change_15m
        signal.volume_ratio = reading.volume_ratio
        signal.rsi = reading.rsi
        signal.liquidations_faded = reading.liquidations_faded
        signal.oi_drop = reading.oi_drop
        signal.oi_change_pct = reading.oi_change_pct
        signal.oi_change_1h_pct = reading.oi_change_1h_pct
        signal.oi_change_4h_pct = reading.oi_change_4h_pct
        signal.volume_faded = reading.volume_faded
        signal.sweep = reading.sweep
        signal.sweep_timeframes = list(reading.sweep_timeframes)
        signal.mega_level = reading.mega_level
        signal.round_level = reading.round_level
        signal.cvd_divergence = reading.cvd_divergence
        signal.taker_ratio = _finite(reading.taker_ratio)
        signal.obv_divergence = reading.obv_divergence
        signal.funding_rate = reading.funding_rate
        signal.chart_levels = list(reading.chart_levels)
        signal.round_prices = list(reading.round_prices)
        signal.pnl_pct = short_pnl_pct(signal.entry_price, signal.last_price)

    def _confirmed_signal_strength(self, symbol: str, candidate: int, now_ms: int) -> int:
        current = self.open_signals.get(symbol)
        if current is None:
            return candidate
        confirmed = int(current.strength)
        if candidate == confirmed:
            self._signal_column_pending.pop(symbol, None)
            return confirmed
        pending = self._signal_column_pending.get(symbol)
        if pending is None or pending[0] != candidate:
            self._signal_column_pending[symbol] = (candidate, now_ms)
            return confirmed
        need = (
            config.WATCH_STAGE_CONFIRM_MS
            if candidate > confirmed
            else config.WATCH_STAGE_DOWN_CONFIRM_MS
        )
        if now_ms - pending[1] >= need:
            self._signal_column_pending.pop(symbol, None)
            return candidate
        return confirmed

    def _board(self, now_ms: int) -> dict:
        grouped: dict[int, list[Signal]] = {level: [] for level in (5, 4, 3, 2, 1)}
        for signal in self.open_signals.values():
            state = self.symbols.get(signal.symbol)
            if state is not None and not _meets_turnover(state):
                continue
            grouped[signal.strength].append(signal)
        columns = []
        for level in (5, 4, 3, 2, 1):
            column = column_for(level)
            ordered = sorted(grouped[level], key=lambda item: item.rating, reverse=True)
            columns.append({**column, "signals": [item.to_data() for item in ordered]})
        return {"type": "board", "timestamp": now_ms, "data": {"columns": columns}}


def _meets_turnover(state: SymbolState) -> bool:
    turnover = state.turnover_24h_usdt
    if turnover is None:
        return False
    return turnover >= config.UNIVERSE_MIN_TURNOVER_24H_USDT


def _signature(signal: Signal) -> tuple:
    return (
        signal.strength,
        signal.liquidations_faded,
        signal.oi_drop,
        signal.volume_faded,
        signal.sweep,
        tuple(signal.sweep_timeframes),
        signal.mega_level,
        signal.round_level,
        signal.cvd_divergence,
        signal.obv_divergence,
        signal.extra,
        signal.outcome,
        round(signal.rating, 4),
        round(signal.last_price, 8),
    )


def _finite(value: float | None) -> float | None:
    if value is None or value == float("inf") or value != value:
        return None
    return value
