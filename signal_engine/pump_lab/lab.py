"""Цикл лаборатории пампа: эпизоды, фазы, снимки, доска для UI."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import config
from signal_engine.pump_unified import detect_unified_episodes as detect_episodes, meets_unified_turnover, window_ms
from signal_engine.pump_lab.metrics import METRIC_GROUPS, METRIC_LABELS, compute_all_metrics, metrics_summary
from signal_engine.pump_lab.study import STUDY_FIELDS, build_study
from signal_engine.pump_lab.phases import (
    compute_phase,
    drawdown_from_peak_pct,
    is_pump_passed,
)
from signal_engine.pump_lab.store import PumpLabStore
from signal_engine.state import SymbolState

log = logging.getLogger(__name__)

PHASE_COLORS = {"red": "#ff5d73", "yellow": "#f6d365", "green": "#3dd68c", "purple": "#b388ff"}
CLASS_LABELS = {"fast": "Быстрый", "medium": "Средний", "long": "Длинный"}
_PHASE_ORDER = {"green": 0, "yellow": 1, "red": 2}


def _card_priority_sort(card: dict[str, Any]) -> tuple:
    """Зелёные первые (больше «за шорт»), затем жёлтые, красные (больше «против»)."""
    phase = card.get("phase") or "red"
    order = _PHASE_ORDER.get(phase, 3)
    summary = card.get("summary") or {}
    pro = int(summary.get("for_short") or summary.get("bearish") or 0)
    anti = int(summary.get("against_short") or summary.get("bullish") or 0)
    if phase == "red":
        return (order, -anti, -pro, card.get("symbol") or "")
    return (order, -pro, -anti, card.get("symbol") or "")


def _meets_turnover(state: SymbolState) -> bool:
    return meets_unified_turnover(state)


class PumpLab:
    def __init__(self, store: PumpLabStore | None = None) -> None:
        self.store = store or PumpLabStore(config.PUMP_LAB_SQLITE_PATH)
        self._last_scan_mono = 0.0
        self._last_board: dict[str, Any] | None = None

    def open(self) -> None:
        self.store.open()

    def close(self) -> None:
        self.store.close()

    def request_full_scan(self) -> None:
        """Сброс интервала — следующий maybe_scan пересоберёт эпизоды из рынка."""
        self._last_scan_mono = 0.0

    def maybe_scan(self, symbols: dict[str, SymbolState], now_ms: int) -> dict[str, Any] | None:
        now_mono = time.monotonic()
        if self._last_board is not None and now_mono - self._last_scan_mono < config.PUMP_LAB_SCAN_INTERVAL_SEC:
            self._last_board = self.build_board(now_ms)
            return self._last_board
        self._last_scan_mono = now_mono
        self._run(symbols, now_ms)
        self._last_board = self.build_board(now_ms)
        return self._last_board

    def _btc(self, symbols: dict[str, SymbolState]) -> SymbolState | None:
        return symbols.get(config.PAPER_BTC_SYMBOL)

    def _run(self, symbols: dict[str, SymbolState], now_ms: int) -> None:
        btc = self._btc(symbols)
        active = self.store.active_by_symbol()
        for ep in list(active.values()):
            state = symbols.get(ep["symbol"])
            if state is None:
                continue
            peak = float(ep.get("peak_price") or 0)
            peak_ts = int(ep.get("peak_ts") or 0)
            pc = ep.get("pump_class") or "fast"
            if peak > 0 and peak_ts > 0:
                passed, _ = is_pump_passed(state, pc, peak, peak_ts, now_ms)
                if passed:
                    self.store.close_episode(int(ep["id"]), now_ms, "pump_passed")
        active = self.store.active_by_symbol_class()
        seen: set[tuple[str, str]] = set()

        for symbol, state in symbols.items():
            if not _meets_turnover(state):
                continue
            for draft in detect_episodes(state, now_ms):
                key = (symbol, draft.pump_class)
                seen.add(key)
                ep = active.get(key)
                if ep is None:
                    phase, phase_meta = compute_phase(
                        state, draft.pump_class, draft.peak_price, draft.peak_ts, now_ms
                    )
                    if phase == "purple":
                        continue
                    metrics = compute_all_metrics(state, btc, draft.peak_price, draft.peak_ts, now_ms)
                    eid = self.store.insert_episode(
                        {
                            "symbol": symbol,
                            "pump_class": draft.pump_class,
                            "phase": phase,
                            "valley_price": draft.valley_price,
                            "valley_ts": draft.valley_ts,
                            "peak_price": draft.peak_price,
                            "peak_ts": draft.peak_ts,
                            "growth_pct": draft.growth_pct,
                            "started_at": now_ms,
                            "updated_at": now_ms,
                            "phase_since": now_ms,
                            "last_price": state.last_price,
                            "drawdown_pct": phase_meta.get("drawdown_pct"),
                            "metrics": metrics,
                        }
                    )
                    marks = ["sample", "peak"]
                    if phase == "yellow":
                        marks.append("stall")
                    elif phase == "green":
                        marks.append("dump")
                    self._snapshot(
                        eid, now_ms, phase, state, metrics, marks, btc, draft.peak_price, draft.peak_ts, draft.growth_pct
                    )
                    log.info("PumpLab: новый эпизод %s %s %s", symbol, draft.pump_class, phase)
                    continue

                self._update_episode(ep, state, btc, draft, now_ms)

        for key, ep in list(active.items()):
            if key in seen:
                continue
            symbol, pump_class = key
            state = symbols.get(symbol)
            price = state.last_price if state else ep.get("last_price")
            peak = ep.get("peak_price") or 0.0
            if price and peak and drawdown_from_peak_pct(price, peak) > config.PUMP_UNIFIED_MAX_DRAWDOWN_PCT:
                self.store.close_episode(ep["id"], now_ms, "drawdown")
            elif now_ms - int(ep.get("peak_ts") or now_ms) > window_ms(pump_class):
                self.store.close_episode(ep["id"], now_ms, "age")
            elif state is not None:
                # Детектор больше не видит памп, карточка ещё на доске — журнал всё равно пишем.
                self._refresh_tracked(ep, state, btc, now_ms)

    def _update_episode(
        self,
        ep: dict[str, Any],
        state: SymbolState,
        btc: SymbolState | None,
        draft: Any,
        now_ms: int,
    ) -> None:
        peak_price = max(float(ep.get("peak_price") or 0), draft.peak_price)
        peak_ts = (
            draft.peak_ts
            if draft.peak_price >= float(ep.get("peak_price") or 0)
            else int(ep.get("peak_ts") or draft.peak_ts)
        )
        pump_class = draft.pump_class
        phase, phase_meta = compute_phase(state, pump_class, peak_price, peak_ts, now_ms)
        if phase == "purple":
            self.store.close_episode(int(ep["id"]), now_ms, "pump_passed")
            log.info("PumpLab: %s памп прошёл (откат %.1f%%)", ep.get("symbol"), phase_meta.get("drawdown_pct"))
            return
        phase_since = int(ep.get("phase_since") or now_ms)
        if phase != ep.get("phase"):
            phase_since = now_ms
        metrics = compute_all_metrics(state, btc, peak_price, peak_ts, now_ms)
        row = {
            "pump_class": pump_class,
            "phase": phase,
            "updated_at": now_ms,
            "peak_price": peak_price,
            "peak_ts": peak_ts,
            "growth_pct": draft.growth_pct,
            "phase_since": phase_since,
            "last_price": state.last_price,
            "drawdown_pct": phase_meta.get("drawdown_pct"),
            "metrics": metrics,
            "valley_price": min(float(ep.get("valley_price") or draft.valley_price), draft.valley_price),
            "valley_ts": min(int(ep.get("valley_ts") or draft.valley_ts), draft.valley_ts),
        }
        self.store.update_episode(int(ep["id"]), row)
        marks = ["sample"]
        if peak_ts != int(ep.get("peak_ts") or 0):
            marks.append("peak")
        if phase != ep.get("phase"):
            if phase == "yellow":
                marks.append("stall")
            elif phase == "green":
                marks.append("dump")
        self._snapshot(
            int(ep["id"]), now_ms, phase, state, metrics, marks, btc, peak_price, peak_ts, draft.growth_pct
        )

        price = state.last_price or peak_price
        if drawdown_from_peak_pct(price, peak_price) > config.PUMP_UNIFIED_MAX_DRAWDOWN_PCT:
            self.store.close_episode(int(ep["id"]), now_ms, "drawdown")

    def _refresh_tracked(
        self,
        ep: dict[str, Any],
        state: SymbolState,
        btc: SymbolState | None,
        now_ms: int,
    ) -> None:
        fresh = self.store.episode(int(ep["id"]))
        if fresh is None or fresh.get("status") != "active":
            return
        peak_price = float(ep.get("peak_price") or 0)
        peak_ts = int(ep.get("peak_ts") or 0)
        pump_class = ep.get("pump_class") or "fast"
        if peak_price <= 0 or peak_ts <= 0:
            return
        phase, phase_meta = compute_phase(state, pump_class, peak_price, peak_ts, now_ms)
        if phase == "purple":
            self.store.close_episode(int(ep["id"]), now_ms, "pump_passed")
            return
        phase_since = int(ep.get("phase_since") or now_ms)
        if phase != ep.get("phase"):
            phase_since = now_ms
        metrics = compute_all_metrics(state, btc, peak_price, peak_ts, now_ms)
        self.store.update_episode(
            int(ep["id"]),
            {
                "pump_class": pump_class,
                "phase": phase,
                "updated_at": now_ms,
                "peak_price": peak_price,
                "peak_ts": peak_ts,
                "growth_pct": ep.get("growth_pct"),
                "phase_since": phase_since,
                "last_price": state.last_price,
                "drawdown_pct": phase_meta.get("drawdown_pct"),
                "metrics": metrics,
                "valley_price": ep.get("valley_price"),
                "valley_ts": ep.get("valley_ts"),
            },
        )
        marks = ["sample"]
        if phase != ep.get("phase"):
            if phase == "yellow":
                marks.append("stall")
            elif phase == "green":
                marks.append("dump")
        self._snapshot(int(ep["id"]), now_ms, phase, state, metrics, marks, btc, peak_price, peak_ts, ep.get("growth_pct"))

    def _snapshot(
        self,
        episode_id: int,
        ts: int,
        phase: str,
        state: SymbolState,
        metrics: dict,
        marks: list[str],
        btc: SymbolState | None,
        peak_price: float,
        peak_ts: int,
        growth_pct: float | None,
    ) -> None:
        price = state.last_price
        dd = drawdown_from_peak_pct(price or 0, peak_price) if peak_price else None
        self.store.insert_snapshot(episode_id, ts, phase, price, dd, metrics)
        self.store.append_metric_points(episode_id, ts, metrics)
        features = build_study(state, btc, peak_price, peak_ts, ts, growth_pct)
        for mark in marks:
            self.store.insert_study(episode_id, ts, mark, phase, price, features)

    def build_board(self, now_ms: int) -> dict[str, Any]:
        sections: dict[str, list[dict[str, Any]]] = {"fast": [], "medium": [], "long": []}
        for ep in self.store.active_episodes():
            phase = ep.get("phase") or "red"
            if phase == "purple":
                continue
            pump_class = ep.get("pump_class") or "fast"
            if pump_class not in sections:
                pump_class = "fast"
            metrics = {}
            try:
                metrics = json.loads(ep.get("metrics_json") or "{}")
            except json.JSONDecodeError:
                metrics = {}
            summary = metrics_summary(metrics) if metrics else {"bearish": 0, "bullish": 0, "filled": 0, "total_cells": 90}
            card = {
                "episode_id": ep["id"],
                "symbol": ep["symbol"],
                "pump_class": pump_class,
                "pump_class_label": CLASS_LABELS.get(pump_class, pump_class),
                "phase": phase,
                "phase_color": PHASE_COLORS.get(phase, "#8d97a8"),
                "phase_label": {
                    "red": "Рост",
                    "yellow": "Торможение",
                    "green": "Снижение",
                    "purple": "Памп прошёл",
                }.get(phase, phase),
                "growth_pct": ep.get("growth_pct"),
                "drawdown_pct": ep.get("drawdown_pct"),
                "last_price": ep.get("last_price"),
                "peak_price": ep.get("peak_price"),
                "updated_at": ep.get("updated_at"),
                "summary": summary,
            }
            sections[pump_class].append(card)
        for key in sections:
            sections[key].sort(key=_card_priority_sort)
        return {
            "updated_at": now_ms,
            "sections": sections,
            "metric_labels": METRIC_LABELS,
            "metric_groups": [{"id": g[0], "title": g[1]} for g in METRIC_GROUPS],
            "horizon_labels": {"short": "Короткий", "mid": "Средний", "long": "Длинный"},
            "study_field_count": len(STUDY_FIELDS),
        }

    def board_message(self, now_ms: int) -> dict[str, Any]:
        board = self._last_board or self.build_board(now_ms)
        return {"type": "pump_lab_board", "data": board}
