"""Скан: бумажные стратегии (вкладка «Тест»). Доска «Анализ пампа» снята."""

from __future__ import annotations

import logging

from signal_engine.paper.strategy import PaperStrategy
from signal_engine.state import SymbolState
from signal_engine.store import SignalStore


log = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        store: SignalStore,
        paper: PaperStrategy | None = None,
    ) -> None:
        self.store = store
        self.paper = paper
        self.symbols: dict[str, SymbolState] = {}

    def restore(self) -> None:
        if self.paper is not None:
            self.paper.open()
            for sym in self.paper.bab_open_symbols():
                self.symbols.setdefault(sym, SymbolState(sym))

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
        if self.paper is not None:
            try:
                out.append(self.paper.scan(self.symbols, now_ms, pivots=pivots))
            except Exception:
                log.exception("Тест стратегии: ошибка скана")
        return out
