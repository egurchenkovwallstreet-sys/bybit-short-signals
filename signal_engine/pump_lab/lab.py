"""Цикл лаборатории пампа: эпизоды, фазы, снимки, доска для UI."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import config
from signal_engine.pump_lab.detect import detect_episode
from signal_engine.pump_lab.metrics import METRIC_GROUPS, METRIC_LABELS, compute_all_metrics, metrics_summary
from signal_engine.pump_lab.phases import (
    compute_phase,
    drawdown_from_peak_pct,
    is_pump_passed,
    pump_class_from_duration,
)
from signal_engine.pump_lab.store import PumpLabStore
from signal_engine.state import SymbolState

log = logging.getLogger(__name__)

PHASE_COLORS = {"red": "#ff5d73", "yellow": "#f6d365", "green": "#3dd68c", "purple": "#b388ff"}
CLASS_LABELS = {"fast": "Быстрый", "medium": "Средний", "long": "Длинный"}


def _meets_turnover(state: SymbolState) -> bool:
    turnover = state.turnover_24h_usdt
    if turnover is None:
        return True
    return turnover >= config.UNIVERSE_MIN_TURNOVER_24H_USDT


class PumpLab:
    def __init__(self, store: PumpLabStore | None = None) -> None:
        self.store = store or PumpLabStore(config.PUMP_LAB_SQLITE_PATH)
        self._last_scan_mono = 0.0
        self._last_board: dict[str, Any] | None = None

    def open(self) -> None:
        self.store.open()

    def close(self) -> None:
        self.store.close()

    def maybe_scan(self, symbols: dict[str, SymbolState], now_ms: int) -> dict[str, Any] | None:
        now_mono = time.monotonic()
        if self._last_board is not None and now_mono - self._last_scan_mono < config.PUMP_LAB_SCAN_INTERVAL_SEC:
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
        active = self.store.active_by_symbol()
        seen: set[str] = set()

        for symbol, state in symbols.items():
            if not _meets_turnover(state):
                continue
            draft = detect_episode(state, now_ms)
            if draft is None:
                continue
            seen.add(symbol)
            ep = active.get(symbol)
            if ep is None:
                phase, phase_meta = compute_phase(state, draft.pump_class, draft.peak_price, draft.peak_ts, now_ms)
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
                self._snapshot(eid, now_ms, phase, state, metrics)
                log.info("PumpLab: новый эпизод %s %s %s", symbol, draft.pump_class, phase)
                continue

            self._update_episode(ep, state, btc, draft, now_ms)

        max_age = config.PUMP_LAB_MAX_AGE_DAYS * 24 * 3_600_000
        for symbol, ep in list(active.items()):
            if symbol in seen:
                continue
            state = symbols.get(symbol)
            price = state.last_price if state else ep.get("last_price")
            peak = ep.get("peak_price") or 0.0
            if price and peak and drawdown_from_peak_pct(price, peak) > config.PUMP_LAB_MAX_DRAWDOWN_PCT:
                self.store.close_episode(ep["id"], now_ms, "drawdown")
            elif now_ms - int(ep.get("peak_ts") or now_ms) > max_age:
                self.store.close_episode(ep["id"], now_ms, "age")

    def _update_episode(
        self,
        ep: dict[str, Any],
        state: SymbolState,
        btc: SymbolState | None,
        draft: Any,
        now_ms: int,
    ) -> None:
        peak_price = max(float(ep.get("peak_price") or 0), draft.peak_price)
        peak_ts = draft.peak_ts if draft.peak_price >= float(ep.get("peak_price") or 0) else int(ep.get("peak_ts") or draft.peak_ts)
        duration = max(0, peak_ts - int(ep.get("valley_ts") or draft.valley_ts))
        pump_class = pump_class_from_duration(duration)
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
        self._snapshot(int(ep["id"]), now_ms, phase, state, metrics)

        price = state.last_price or peak_price
        if drawdown_from_peak_pct(price, peak_price) > config.PUMP_LAB_MAX_DRAWDOWN_PCT:
            self.store.close_episode(int(ep["id"]), now_ms, "drawdown")

    def _snapshot(self, episode_id: int, ts: int, phase: str, state: SymbolState, metrics: dict) -> None:
        price = state.last_price
        peak = None
        ep = self.store.episode(episode_id)
        if ep:
            peak = ep.get("peak_price")
        dd = drawdown_from_peak_pct(price or 0, peak or 0) if peak else None
        self.store.insert_snapshot(episode_id, ts, phase, price, dd, metrics)
        self.store.append_metric_points(episode_id, ts, metrics)

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
            sections[key].sort(key=lambda c: (-(c.get("growth_pct") or 0), c.get("symbol") or ""))
        return {
            "updated_at": now_ms,
            "sections": sections,
            "metric_labels": METRIC_LABELS,
            "metric_groups": [{"id": g[0], "title": g[1]} for g in METRIC_GROUPS],
            "horizon_labels": {"short": "Короткий", "mid": "Средний", "long": "Длинный"},
        }

    def board_message(self, now_ms: int) -> dict[str, Any]:
        board = self._last_board or self.build_board(now_ms)
        return {"type": "pump_lab_board", "data": board}
