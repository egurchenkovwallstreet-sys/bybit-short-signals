"""График: памп как мини-тест, вход по lower high на 15m (выход как t20)."""

from __future__ import annotations

import config
from signal_engine.paper.detect import MIN_MS, _check, _r, grade_for
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import absolute_high_since, closed_bars, pivot_highs_indexed

GRAF_MANDATORY = (
    "trigger_4h_24h",
    "main_high",
    "lower_high",
    "confirm_close",
)

GRAF_CHECK_LABELS = {
    "trigger_4h_24h": "Памп только 4ч или сутки (пороги мини)",
    "main_high": "Есть абсолютный хай пампа на 15m",
    "lower_high": "Вторая вершина — локальный хай ниже главного",
    "confirm_close": "След. 15m закрылась ниже close второй вершины",
}


def _bars15(state: SymbolState) -> list[Bar]:
    raw = state.bars_htf.get("15") or []
    return [
        Bar(b.timestamp, b.open, b.high, b.low, b.close, b.volume)
        for b in raw
    ]


def _local_high_at(bars: list[Bar], i: int, wing: int) -> bool:
    if i - wing < 0 or i + wing >= len(bars):
        return False
    high = bars[i].high
    for j in range(i - wing, i):
        if high <= bars[j].high:
            return False
    for j in range(i + 1, i + wing + 1):
        if high <= bars[j].high:
            return False
    return True


def evaluate_grafik(
    state: SymbolState,
    pump,
    now_ms: int,
    score: float,
    strict_btc: bool,
) -> dict:
    pump_data = pump.to_data() if hasattr(pump, "to_data") else (pump or {})
    trigger = str(pump_data.get("trigger") or getattr(pump, "trigger", "") or "")
    bars = _bars15(state)
    closed = closed_bars(bars, "15", now_ms)
    pump_start = int(getattr(pump, "valley_ts", 0) or pump_data.get("valley_ts") or 0)
    if pump_start <= 0:
        pump_start = int(getattr(pump, "peak_ts", 0) or pump_data.get("peak_ts") or 0)

    segment = [b for b in closed if b.timestamp >= pump_start]
    wing = config.PAPER_GRAF_PIVOT_WING

    abs_row = absolute_high_since(bars, pump_start, "15", now_ms)
    main_high = abs_row[0] if abs_row else None
    main_ts = abs_row[1] if abs_row else None

    confirm_i = len(segment) - 1
    vertex_i = confirm_i - 1
    vertex = segment[vertex_i] if vertex_i >= 0 else None
    confirm = segment[confirm_i] if confirm_i >= 0 else None

    abs_idx = None
    if main_high is not None and main_ts is not None and segment:
        for i, b in enumerate(segment):
            if b.timestamp == main_ts:
                abs_idx = i
                break
        if abs_idx is None:
            for i, b in enumerate(segment):
                if b.high >= main_high - 1e-12:
                    abs_idx = i
                    break

    peak_unbroken = True
    if abs_idx is not None and vertex_i >= 0:
        for j in range(abs_idx + 1, vertex_i + 1):
            if segment[j].high > main_high + 1e-12:
                peak_unbroken = False
                break

    lower_ok = False
    if (
        vertex is not None
        and confirm is not None
        and main_high is not None
        and abs_idx is not None
        and vertex_i > abs_idx
        and peak_unbroken
        and vertex.high < main_high - 1e-12
        and _local_high_at(segment, vertex_i, wing)
    ):
        lower_ok = True

    confirm_ok = (
        lower_ok
        and confirm.close < vertex.close - 1e-12
        and confirm.timestamp + 15 * MIN_MS <= now_ms
    )

    checks = {
        "trigger_4h_24h": _check(trigger in config.PAPER_MINI_TRIGGERS, trigger or "нет", "4h или 24h"),
        "main_high": _check(
            main_high is not None and abs_idx is not None,
            None if main_high is None else _r(main_high, 6),
            "максимум 15m с начала роста",
        ),
        "lower_high": _check(
            lower_ok,
            None
            if vertex is None
            else {"high": _r(vertex.high, 6), "main": _r(main_high, 6) if main_high else None},
            "локальный хай ниже главного",
        ),
        "confirm_close": _check(
            confirm_ok,
            None
            if confirm is None or vertex is None
            else {"close": _r(confirm.close, 6), "vertex_close": _r(vertex.close, 6)},
            "close следующей 15m < close вершины",
        ),
    }
    failed = [k for k in GRAF_MANDATORY if not checks[k]["ok"]]
    passed = not failed
    metrics = {
        "pump": pump_data,
        "main_high": main_high,
        "main_high_ts": main_ts,
        "vertex_ts": vertex.timestamp if vertex else None,
        "confirm_ts": confirm.timestamp if confirm else None,
        "pivot_wing": wing,
    }
    if passed and segment:
        pivots = pivot_highs_indexed(segment, wing)
        metrics["pivots_count"] = len(pivots)

    return {
        "checks": checks,
        "metrics": metrics,
        "score": round(score, 1),
        "grade": grade_for(score),
        "strict_btc": strict_btc,
        "passed": passed,
        "passed_count": len(GRAF_MANDATORY) - len(failed),
        "failed": failed,
        "variants": [config.PAPER_GRAF_VARIANT] if passed else [],
        "entry_blocked": [],
    }
