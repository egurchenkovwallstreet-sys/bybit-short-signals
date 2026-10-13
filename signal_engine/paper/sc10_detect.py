"""Скальп 10: вход на старте 1м-хода, лонг и шорт, трейл 10% ROE.

t20/p10/lt20/css этот модуль не используют.
"""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.flow import oi_change_pct
from signal_engine.paper.detect import MIN_MS, _check, _r, grade_for
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState

SC10_MANDATORY = (
    "range_break",
    "volume_spike",
    "tape_side",
    "oi_ok",
    "btc_ok",
    "follow_through",
)

SC10_CHECK_LABELS = {
    "range_break": "Закрытая 1м пробила диапазон",
    "volume_spike": "Объём минутки ×3+ и выше предыдущих",
    "tape_side": "Агрессия ленты в сторону хода",
    "oi_ok": "OI растёт",
    "btc_ok": "Не против BTC",
    "follow_through": "Цена держит пробой",
}


def closed_1m_bars(state: SymbolState, now_ms: int) -> list[Bar]:
    bars = list(state.bars_1m)
    if not bars:
        return []
    if bars[-1].timestamp + MIN_MS > now_ms:
        return bars[:-1]
    return bars


def btc_move_pct(state: SymbolState | None, now_ms: int, minutes: int) -> float | None:
    if state is None:
        return None
    closed = closed_1m_bars(state, now_ms)
    if len(closed) < minutes + 1:
        return None
    old = closed[-1 - minutes].close
    last = closed[-1].close
    if old <= 0:
        return None
    return (last / old - 1.0) * 100.0


@dataclass
class Sc10Evaluation:
    checks: dict[str, dict]
    metrics: dict
    score: float
    side: str | None

    @property
    def passed(self) -> bool:
        return self.side in ("long", "short") and all(self.checks[k]["ok"] for k in SC10_MANDATORY)

    @property
    def failed(self) -> list[str]:
        return [k for k in SC10_MANDATORY if not self.checks[k]["ok"]]

    @property
    def passed_count(self) -> int:
        return len(SC10_MANDATORY) - len(self.failed)

    def to_data(self) -> dict:
        return {
            "checks": self.checks,
            "metrics": self.metrics,
            "score": round(self.score, 1),
            "grade": grade_for(self.score),
            "strict_btc": False,
            "passed": self.passed,
            "passed_count": self.passed_count,
            "failed": self.failed,
            "variants": [config.PAPER_SC10_VARIANT] if self.passed else [],
            "entry_blocked": [],
            "side": self.side,
        }


def _empty_checks() -> dict[str, dict]:
    return {
        "range_break": _check(False, None, "закрытая 1м за хай/лой диапазона"),
        "volume_spike": _check(False, None, f"объём ×{config.PAPER_SC10_VOLUME_MIN_RATIO:g}"),
        "tape_side": _check(False, None, f"доля ≥ {config.PAPER_SC10_TAKER_SHARE_MIN_PCT:g}%"),
        "oi_ok": _check(False, None, f"OI ≥ +{config.PAPER_SC10_OI_MIN_PCT:g}%"),
        "btc_ok": _check(False, None, "не против BTC"),
        "follow_through": _check(False, None, "цена всё ещё за диапазоном"),
    }


def evaluate_sc10(
    state: SymbolState,
    tape: SymbolTape,
    btc_state: SymbolState | None,
    now_ms: int,
) -> Sc10Evaluation:
    checks: dict[str, dict] = {}
    closed = closed_1m_bars(state, now_ms)
    lookback = config.PAPER_SC10_RANGE_BARS
    vol_n = config.PAPER_SC10_VOLUME_BARS
    metrics: dict = {
        "pump": {"kind": "sc10", "side": None},
        "last_price": float(state.last_price or 0),
    }
    empty = _empty_checks()
    if len(closed) < lookback + 2:
        return Sc10Evaluation(checks=empty, metrics=metrics, score=0.0, side=None)

    bar = closed[-1]
    prior = closed[-(lookback + 1) : -1]
    rng_high = max(b.high for b in prior)
    rng_low = min(b.low for b in prior)
    body = abs(bar.close - bar.open)
    rng = bar.high - bar.low
    body_ratio = body / rng if rng > 0 else 0.0
    bull = (
        bar.close > rng_high
        and bar.close > bar.open
        and body_ratio >= config.PAPER_SC10_BODY_MIN_RATIO
    )
    bear = (
        bar.close < rng_low
        and bar.close < bar.open
        and body_ratio >= config.PAPER_SC10_BODY_MIN_RATIO
    )
    side = "long" if bull else "short" if bear else None
    checks["range_break"] = _check(
        side is not None,
        {
            "close": bar.close,
            "range_high": rng_high,
            "range_low": rng_low,
            "body_ratio": _r(body_ratio, 2),
            "side": side,
        },
        f"закрытие 1м за диапазон {lookback}м, тело ≥ {config.PAPER_SC10_BODY_MIN_RATIO:.0%}",
    )

    base = closed[-(vol_n + 1) : -1]
    mean_vol = sum(b.volume for b in base) / len(base) if base else 0.0
    vol_ratio = bar.volume / mean_vol if mean_vol > 0 else None
    dom_n = config.PAPER_SC10_VOL_DOMINATE_BARS
    prev_vols = [b.volume for b in closed[-(dom_n + 1) : -1]]
    vol_max_prev = max(prev_vols) if prev_vols else 0.0
    vol_ok = (
        vol_ratio is not None
        and vol_ratio >= config.PAPER_SC10_VOLUME_MIN_RATIO
        and bar.volume > vol_max_prev
    )
    checks["volume_spike"] = _check(
        vol_ok,
        {"ratio": _r(vol_ratio, 2), "vs_prev": _r(bar.volume / vol_max_prev if vol_max_prev > 0 else None, 2)},
        f"≥ ×{config.PAPER_SC10_VOLUME_MIN_RATIO:g} к средней {vol_n}м и выше {dom_n} предыдущих",
    )

    tape_now = bar.timestamp + MIN_MS - 1
    shares: dict[str, float | None] = {}
    tape_ok = True
    need = config.PAPER_SC10_TAKER_SHARE_MIN_PCT
    for minutes in (1, config.PAPER_SC10_TAKER_MINUTES):
        buy, sell = tape.minute_window(tape_now, minutes)
        total = buy + sell
        if total <= 0:
            shares[f"{minutes}m"] = None
            tape_ok = False
            continue
        share = (buy / total * 100.0) if side == "long" else (sell / total * 100.0)
        shares[f"{minutes}m"] = _r(share, 1)
        if share < need:
            tape_ok = False
    if side is None:
        tape_ok = False
    checks["tape_side"] = _check(
        tape_ok,
        shares,
        f"тейкеры в сторону хода ≥ {need:g}% за 1 и {config.PAPER_SC10_TAKER_MINUTES}м",
    )

    oi_pct = oi_change_pct(state.oi_points(), lookback_min=config.PAPER_SC10_OI_LOOKBACK_MIN)
    oi_need = config.PAPER_SC10_OI_MIN_PCT
    checks["oi_ok"] = _check(
        oi_pct is not None and oi_pct >= oi_need,
        _r(oi_pct, 2),
        f"OI {config.PAPER_SC10_OI_LOOKBACK_MIN:g}м ≥ +{oi_need:g}%",
    )

    btc_pct = btc_move_pct(btc_state, now_ms, config.PAPER_SC10_BTC_MINUTES)
    against = config.PAPER_SC10_BTC_AGAINST_PCT
    if state.symbol == config.PAPER_BTC_SYMBOL:
        btc_ok = True
        btc_need = "BTC сам по себе"
    elif side == "long":
        btc_ok = btc_pct is not None and btc_pct >= -against
        btc_need = f"BTC {config.PAPER_SC10_BTC_MINUTES}м ≥ −{against:g}%"
    elif side == "short":
        btc_ok = btc_pct is not None and btc_pct <= against
        btc_need = f"BTC {config.PAPER_SC10_BTC_MINUTES}м ≤ +{against:g}%"
    else:
        btc_ok = False
        btc_need = "сначала пробой"
    checks["btc_ok"] = _check(btc_ok, _r(btc_pct, 2), btc_need)

    last = float(state.last_price or 0)
    break_min = config.PAPER_SC10_BREAK_MIN_PCT
    ext_pct = None
    if side == "long" and rng_high > 0:
        ext_pct = (bar.close / rng_high - 1.0) * 100.0
        hold = last >= rng_high and last >= bar.close * 0.998
        ft_ok = ext_pct >= break_min and hold
    elif side == "short" and rng_low > 0:
        ext_pct = (1.0 - bar.close / rng_low) * 100.0
        hold = last <= rng_low and last <= bar.close * 1.002
        ft_ok = ext_pct >= break_min and hold
    else:
        ft_ok = False
    checks["follow_through"] = _check(
        ft_ok,
        {"last": last, "ext_pct": _r(ext_pct, 2)},
        f"пробой ≥ {break_min:g}% и цена не вернулась в диапазон",
    )

    metrics.update(
        {
            "pump": {
                "kind": "sc10",
                "side": side,
                "bar_ts": bar.timestamp,
                "close": bar.close,
                "range_high": rng_high,
                "range_low": rng_low,
                "volume_ratio": _r(vol_ratio, 2),
            },
            "since_peak_min": 0,
            "sell_share": shares if side == "short" else None,
            "buy_share": shares if side == "long" else shares,
            "oi_15m_pct": _r(oi_pct, 2),
            "btc_5m_pct": _r(btc_pct, 2),
            "range_pct": _r((rng_high / rng_low - 1.0) * 100.0 if rng_low > 0 else None, 2),
            "ext_pct": _r(ext_pct, 2),
        }
    )
    score = sum(100.0 / len(SC10_MANDATORY) for k in SC10_MANDATORY if checks[k]["ok"])
    return Sc10Evaluation(checks=checks, metrics=metrics, score=score, side=side)
