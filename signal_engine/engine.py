"""Скан: бумажные стратегии и доска «Памп сигналы»."""

from __future__ import annotations

import logging

from signal_engine.live.em6_bybit.strategy import Em6BybitStrategy
from signal_engine.paper.strategy import PaperStrategy
from signal_engine.pump_signals import build_pump_signals_board
from signal_engine.state import SymbolState
from signal_engine.store import SignalStore
from signal_engine.watch_store import WatchStore
import config


log = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        store: SignalStore,
        paper: PaperStrategy | None = None,
        em6_bybit: Em6BybitStrategy | None = None,
        watches: WatchStore | None = None,
    ) -> None:
        self.store = store
        self.paper = paper
        self.em6_bybit = em6_bybit
        self.watches = watches or WatchStore(config.SQLITE_PATH)
        self.symbols: dict[str, SymbolState] = {}

    def restore(self) -> None:
        self.watches.open()
        if self.paper is not None:
            self.paper.open()
            for sym in self.paper.bab_open_symbols():
                self.symbols.setdefault(sym, SymbolState(sym))
        if self.em6_bybit is not None:
            self.em6_bybit.open()

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

    def scan(self, now_ms: int, *, boards: bool = True, pivots: bool = True) -> list[dict]:
        out: list[dict] = []
        if self.paper is not None and config.paper_test_enabled():
            try:
                out.append(self.paper.scan(self.symbols, now_ms, pivots=pivots))
            except Exception:
                log.exception("Тест стратегии: ошибка скана")
        if boards:
            try:
                out.append(
                    build_pump_signals_board(
                        self.symbols,
                        now_ms,
                        self.watches,
                        self.paper,
                    )
                )
            except Exception:
                log.exception("Памп сигналы: ошибка скана")
        return out
