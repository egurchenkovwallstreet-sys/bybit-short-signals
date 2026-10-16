"""Импульс: вход по закрытой свече 5м или 15м, лонг и шорт.

Объём свечи строго больше ×3 предыдущей, закрытие в сторону сделки,
агрессия ленты на этой свече в ту же сторону строго больше 60%.
Выход ведёт position со стилем impulse — те же ступени, что у Трейл 20.
"""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.paper.detect import MIN_MS, _check, _r, grade_for
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState

IMPULSE_MANDATORY = (
    "volume_x3",
    "price_side",
    "flow_side",
)

IMPULSE5_EXTRA_MANDATORY = (
    "body_min",
    "close_strength",
    "no_snapback",
)

IMPULSE_CHECK_LABELS = {
    "volume_x3": f"Объём свечи > ×{config.PAPER_IMPULSE_VOLUME_MIN_RATIO:g} предыдущей",
    "price_side": "Закрытие свечи в сторону сделки",
    "flow_side": f"Агрессия в сторону сделки > {config.PAPER_IMPULSE_FLOW_MIN_PCT:g}%",
    "body_min": f"Тело 5m ≥ {config.PAPER_IMP5_MIN_BODY_PCT:g}% (импульс к локу +3% ROE)",
    "close_strength": f"Закрытие у экстремума свечи (≤ {config.PAPER_IMP5_CLOSE_EDGE_MAX * 100:g}% диапазона)",
    "no_snapback": f"Цена не откатила > {config.PAPER_IMP5_MAX_SNAPBACK_PCT:g}% от close импульса",
}


def impulse_mandatory(minutes: int) -> tuple[str, ...]:
    if minutes == 5:
        return IMPULSE_MANDATORY + IMPULSE5_EXTRA_MANDATORY
    return IMPULSE_MANDATORY


@dataclass
class ImpulseEvaluation:
    checks: dict[str, dict]
    metrics: dict
    score: float
    side: str | None
    minutes: int

    @property
    def passed(self) -> bool:
        keys = impulse_mandatory(self.minutes)
        return self.side in ("long", "short") and all(self.checks.get(k, {}).get("ok") for k in keys)

    @property
    def failed(self) -> list[str]:
        keys = impulse_mandatory(self.minutes)
        return [k for k in keys if not self.checks.get(k, {}).get("ok")]

    @property
    def passed_count(self) -> int:
        keys = impulse_mandatory(self.minutes)
        return len(keys) - len(self.failed)

    def to_data(self) -> dict:
        variant = config.PAPER_IMP5_VARIANT if self.minutes == 5 else config.PAPER_IMP15_VARIANT
        return {
            "checks": self.checks,
            "metrics": self.metrics,
            "score": round(self.score, 1),
            "grade": grade_for(self.score),
            "strict_btc": False,
            "passed": self.passed,
            "passed_count": self.passed_count,
            "failed": self.failed,
            "variants": [variant] if self.passed and variant in config.PAPER_VARIANTS else [],
            "entry_blocked": [],
            "side": self.side,
        }


def _closed_buckets(state: SymbolState, now_ms: int, minutes: int) -> list[Bar]:
    step = minutes * MIN_MS
    grouped: dict[int, dict[int, Bar]] = {}
    for bar in state.bars_1m:
        key = (int(bar.timestamp) // step) * step
        grouped.setdefault(key, {})[int(bar.timestamp)] = bar
    closed: list[Bar] = []
    for key in sorted(grouped):
        if key + step > now_ms:
            continue
        rows = [grouped[key][ts] for ts in sorted(grouped[key])]
        if len(rows) < minutes:
            continue
        closed.append(
            Bar(
                key,
                rows[0].open,
                max(row.high for row in rows),
                min(row.low for row in rows),
                rows[-1].close,
                sum(row.volume for row in rows),
            )
        )
    return closed


def _candle_flow(tape: SymbolTape | None, start_ms: int, end_ms: int) -> tuple[float, float]:
    if tape is None:
        return 0.0, 0.0
    buy = sell = 0.0
    for key, row in tape.minutes.items():
        if start_ms <= int(key) < end_ms:
            buy += float(row[0])
            sell += float(row[1])
    return buy, sell


def evaluate_impulse(
    state: SymbolState,
    tape: SymbolTape | None,
    now_ms: int,
    minutes: int,
) -> ImpulseEvaluation:
    checks: dict[str, dict] = {}
    bars = _closed_buckets(state, now_ms, minutes)
    last = bars[-1] if bars else None
    prev = bars[-2] if len(bars) >= 2 else None
    step = minutes * MIN_MS
    ratio_need = config.PAPER_IMPULSE_VOLUME_MIN_RATIO
    flow_need = config.PAPER_IMPULSE_FLOW_MIN_PCT
    ratio = None
    if last is not None and prev is not None and prev.volume > 0:
        ratio = last.volume / prev.volume
    checks["volume_x3"] = _check(
        ratio is not None and ratio > ratio_need,
        {
            "volume": _r(last.volume, 4) if last else None,
            "prev_volume": _r(prev.volume, 4) if prev else None,
            "ratio": _r(ratio, 2),
            "bars": len(bars),
        },
        f"объём > ×{ratio_need:g} предыдущей закрытой свечи",
    )

    side = None
    if last is not None and last.close > last.open:
        side = "long"
    elif last is not None and last.close < last.open:
        side = "short"
    checks["price_side"] = _check(
        side in ("long", "short"),
        {
            "open": _r(last.open, 8) if last else None,
            "close": _r(last.close, 8) if last else None,
            "side": side,
        },
        "закрытие выше открытия — лонг, ниже — шорт",
    )

    buy = sell = 0.0
    if last is not None:
        buy, sell = _candle_flow(tape, int(last.timestamp), int(last.timestamp) + step)
    total = buy + sell
    share = None
    if side == "long" and total > 0:
        share = buy / total * 100.0
    elif side == "short" and total > 0:
        share = sell / total * 100.0
    checks["flow_side"] = _check(
        share is not None and share > flow_need,
        {"buy": round(buy, 2), "sell": round(sell, 2), "share_pct": _r(share, 1), "side": side},
        f"доля стороны сделки > {flow_need:g}% на этой свече",
    )

    if minutes == 5 and last is not None:
        body_pct = abs(last.close - last.open) / last.open * 100.0 if last.open > 0 else None
        checks["body_min"] = _check(
            body_pct is not None and body_pct >= config.PAPER_IMP5_MIN_BODY_PCT,
            _r(body_pct, 3),
            f"≥ {config.PAPER_IMP5_MIN_BODY_PCT:g}%",
        )
        span = last.high - last.low
        edge = None
        strength_ok = None
        if side in ("long", "short") and span > 0:
            if side == "long":
                edge = (last.high - last.close) / span
            else:
                edge = (last.close - last.low) / span
            strength_ok = edge <= config.PAPER_IMP5_CLOSE_EDGE_MAX
        checks["close_strength"] = _check(
            strength_ok,
            None if edge is None else _r(edge, 3),
            f"≤ {config.PAPER_IMP5_CLOSE_EDGE_MAX:g} доли диапазона",
        )
        last_px = float(state.last_price or last.close)
        snap_ok = None
        snap_pct = None
        if side == "long" and last.close > 0:
            snap_pct = (last_px / last.close - 1.0) * 100.0
            snap_ok = snap_pct >= -config.PAPER_IMP5_MAX_SNAPBACK_PCT
        elif side == "short" and last.close > 0:
            snap_pct = (last_px / last.close - 1.0) * 100.0
            snap_ok = snap_pct <= config.PAPER_IMP5_MAX_SNAPBACK_PCT
        checks["no_snapback"] = _check(
            snap_ok,
            None if snap_pct is None else _r(snap_pct, 3),
            f"лонг: не ниже −{config.PAPER_IMP5_MAX_SNAPBACK_PCT:g}%; шорт: не выше +{config.PAPER_IMP5_MAX_SNAPBACK_PCT:g}%",
        )
    else:
        for key in IMPULSE5_EXTRA_MANDATORY:
            checks[key] = _check(True, "n/a", IMPULSE_CHECK_LABELS[key])

    move = None
    if last is not None and last.open > 0:
        move = (last.close / last.open - 1.0) * 100.0
    metrics = {
        "minutes": minutes,
        "bar_ts": int(last.timestamp) if last else None,
        "volume_ratio": _r(ratio, 2),
        "flow_share_pct": _r(share, 1),
        "pump": {
            "kind": "impulse",
            "side": side,
            "trigger": f"{minutes}m",
            "growth_pct": _r(move, 2),
            "bar_ts": int(last.timestamp) if last else None,
        },
    }
    keys = impulse_mandatory(minutes)
    score = 30.0 * sum(1 for key in keys if checks.get(key, {}).get("ok"))
    return ImpulseEvaluation(checks=checks, metrics=metrics, score=score, side=side, minutes=minutes)
