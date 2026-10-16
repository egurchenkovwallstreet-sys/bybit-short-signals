"""15m: новый LH/HL → pin вверху, подсветка 3 свечи, колонка по правилу max/min."""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from signal_engine.state import SymbolState
from signal_engine.vacuum_lh import (
    _meets_turnover,
    _bars_for_interval,
    _min_bars,
    last_higher_low_troughs,
    last_lower_high_peaks,
    project_peaks_to_chart,
    project_troughs_to_chart,
)

_LIVE_IV = config.VACUUM_LH_LIVE_INTERVAL
_HIGHLIGHT_MS = 3 * 900_000


def _keys(points: list[dict]) -> frozenset[tuple[int, float]]:
    out: set[tuple[int, float]] = set()
    for p in points:
        t = int(p.get("time_ms") or p.get("time") or 0)
        out.add((t, round(float(p["price"]), 8)))
    return frozenset(out)


def snapshot_15m_levels(state: SymbolState, now_ms: int) -> dict | None:
    if not _meets_turnover(state):
        return None
    bars = _bars_for_interval(state, _LIVE_IV)
    if len(bars) < _min_bars(_LIVE_IV):
        return None
    peaks_raw = last_lower_high_peaks(bars, _LIVE_IV, now_ms)
    troughs_raw = last_higher_low_troughs(bars, _LIVE_IV, now_ms)
    return {
        "peaks": project_peaks_to_chart(peaks_raw, _LIVE_IV) if peaks_raw else [],
        "troughs": project_troughs_to_chart(troughs_raw, _LIVE_IV) if len(troughs_raw) >= 2 else [],
    }


def _column_for_new_peak(peaks: list[dict], new_key: tuple[int, float]) -> str | None:
    if len(peaks) < 2:
        return None
    ordered = sorted(peaks, key=lambda p: int(p["time_ms"]))
    idx = next((i for i, p in enumerate(ordered) if (int(p["time_ms"]), round(float(p["price"]), 8)) == new_key), -1)
    if idx < 1:
        return None
    if float(ordered[idx]["price"]) < float(ordered[idx - 1]["price"]):
        return "down"
    return None


def _column_for_new_trough(troughs: list[dict], new_key: tuple[int, float]) -> str | None:
    if len(troughs) < 2:
        return None
    ordered = sorted(troughs, key=lambda p: int(p["time_ms"]))
    idx = next((i for i, p in enumerate(ordered) if (int(p["time_ms"]), round(float(p["price"]), 8)) == new_key), -1)
    if idx < 1:
        return None
    if float(ordered[idx]["price"]) > float(ordered[idx - 1]["price"]):
        return "up"
    return None


def _detect_live_event(prev: dict | None, cur: dict) -> tuple[bool, str | None]:
    if not prev:
        return False, None
    new_peak = _keys(cur["peaks"]) - _keys(prev["peaks"])
    new_trough = _keys(cur["troughs"]) - _keys(prev["troughs"])
    if not new_peak and not new_trough:
        return False, None
    events: list[tuple[int, str | None]] = []
    for key in new_peak:
        events.append((key[0], _column_for_new_peak(cur["peaks"], key)))
    for key in new_trough:
        events.append((key[0], _column_for_new_trough(cur["troughs"], key)))
    events.sort(key=lambda x: x[0])
    return True, events[-1][1]


@dataclass
class VacuumLhLiveStore:
    prev: dict[str, dict] = field(default_factory=dict)
    pins: dict[str, dict] = field(default_factory=dict)
    pin_seq: int = 0

    def update(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for state in states.values():
            sym = state.symbol
            snap = snapshot_15m_levels(state, now_ms)
            if snap is None:
                continue
            prev = self.prev.get(sym)
            has_new, live_col = _detect_live_event(prev, snap)
            if has_new:
                self.pin_seq += 1
                pin: dict = {
                    "live_pin_seq": self.pin_seq,
                    "live_highlight_until_ms": now_ms + _HIGHLIGHT_MS,
                    "live_at_ms": now_ms,
                }
                if live_col:
                    pin["live_column"] = live_col
                self.pins[sym] = pin
            self.prev[sym] = snap

    def attach(self, row: dict) -> dict:
        pin = self.pins.get(str(row.get("symbol") or ""))
        if not pin:
            return row
        out = dict(row)
        out.update(pin)
        return out


def enrich_board_signals(signals: list[dict], store: VacuumLhLiveStore | None) -> list[dict]:
    if not store:
        return signals
    return [store.attach(s) for s in signals]
