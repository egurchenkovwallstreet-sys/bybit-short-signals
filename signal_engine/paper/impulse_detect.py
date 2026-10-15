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

IMPULSE_CHECK_LABELS = {
    "volume_x3": f"Объём свечи > ×{config.PAPER_IMPULSE_VOLUME_MIN_RATIO:g} предыдущей",
    "price_side": "Закрытие свечи в сторону сделки",
    "flow_side": f"Агрессия в сторону сделки > {config.PAPER_IMPULSE_FLOW_MIN_PCT:g}%",
}


@dataclass
class ImpulseEvaluation:
    checks: dict[str, dict]
    metrics: dict
    score: float
    side: str | None
    minutes: int

    @property
    def passed(self) -> bool:
        return self.side in ("long", "short") and all(self.checks[k]["ok"] for k in IMPULSE_MANDATORY)

    @property
    def failed(self) -> list[str]:
        return [k for k in IMPULSE_MANDATORY if not self.checks[k]["ok"]]

    @property
    def passed_count(self) -> int:
        return len(IMPULSE_MANDATORY) - len(self.failed)

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
    score = 30.0 * sum(1 for key in IMPULSE_MANDATORY if checks[key]["ok"])
    return ImpulseEvaluation(checks=checks, metrics=metrics, score=score, side=side, minutes=minutes)
