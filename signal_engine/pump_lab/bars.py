"""Свечи 5m/15m с подмешиванием минуток (как в paper.detect)."""

from __future__ import annotations

from signal_engine.paper.detect import BAR_MS, merged_15m
from signal_engine.state import Bar, SymbolState

MIN_MS = 60_000


def merged_5m(state: SymbolState) -> list[Bar]:
    by_ts = {
        bar.timestamp: Bar(bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume)
        for bar in state.bars_htf.get("5", [])
    }
    minutes = state.bars_1m
    if minutes:
        step = 5 * MIN_MS
        first = minutes[0].timestamp
        groups: dict[int, list[Bar]] = {}
        for bar in minutes:
            key = (bar.timestamp // step) * step
            if key < first and key in by_ts:
                continue
            groups.setdefault(key, []).append(bar)
        for key, rows in groups.items():
            by_ts[key] = Bar(
                key,
                rows[0].open,
                max(r.high for r in rows),
                min(r.low for r in rows),
                rows[-1].close,
                sum(r.volume for r in rows),
            )
    return [by_ts[k] for k in sorted(by_ts)]


def bar_interval_ms(interval: str) -> int:
    if interval == "5":
        return 5 * MIN_MS
    if interval == "15":
        return BAR_MS["15"]
    return 15 * MIN_MS


def is_bar_open(bar_ts: int, interval_ms: int, now_ms: int) -> bool:
    return bar_ts <= now_ms < bar_ts + interval_ms


__all__ = ["merged_5m", "merged_15m", "bar_interval_ms", "is_bar_open"]
