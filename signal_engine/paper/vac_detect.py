"""Пылесос (A-B Short): структура A→C→B на 5m, вход pin+медвежья или 2×медвежья."""

from __future__ import annotations

import config
from signal_engine.paper.detect import _check, _r, grade_for
from signal_engine.paper.swing_1h import pivot_lows_indexed
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars, pivot_highs_indexed

VAC_MANDATORY = (
    "anti_flat",
    "structure_acb",
    "b_confirmed",
    "entry_window",
    "entry_trigger",
    "not_invalidated",
)

VAC_CHECK_LABELS = {
    "anti_flat": "Анти-флэт: ATR, диапазон 20, амплитуды A→C и C→B",
    "structure_acb": "A > B (lower high), есть минимум C между A и B",
    "b_confirmed": "B — swing high с подтверждением 3×3",
    "entry_window": "1–2×5m после подтверждения B",
    "entry_trigger": "Pin+медвежья или две медвежьи подряд",
    "not_invalidated": "После B high не пробивали A и B",
}


def _bars5(state: SymbolState) -> list[Bar]:
    raw = state.bars_htf.get("5") or state.bars or []
    return [Bar(b.timestamp, b.open, b.high, b.low, b.close, b.volume) for b in raw]


def _bearish(bar: Bar) -> bool:
    return float(bar.close) < float(bar.open) - 1e-12


def _atr_pct(bars: list[Bar], period: int) -> float | None:
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        h, l, pc = float(bars[i].high), float(bars[i].low), float(bars[i - 1].close)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    atr = sum(trs[-period:]) / period
    close = float(bars[-1].close)
    if close <= 0:
        return None
    return atr / close * 100.0


def _range_pct(bars: list[Bar], n: int) -> float | None:
    if len(bars) < n:
        return None
    seg = bars[-n:]
    hi = max(float(b.high) for b in seg)
    lo = min(float(b.low) for b in seg)
    close = float(bars[-1].close)
    if close <= 0:
        return None
    return (hi - lo) / close * 100.0


def _is_pin_bar(bar: Bar, wick_ratio: float, body_ratio: float) -> bool:
    rng = float(bar.high) - float(bar.low)
    if rng <= 0:
        return False
    upper = float(bar.high) - max(float(bar.open), float(bar.close))
    body = abs(float(bar.close) - float(bar.open))
    return upper >= wick_ratio * rng and body <= body_ratio * rng


def _entry_trigger(prev: Bar, last: Bar) -> str | None:
    if _is_pin_bar(prev, config.PAPER_VAC_PIN_WICK_RATIO, config.PAPER_VAC_PIN_BODY_RATIO) and _bearish(last):
        return "pin_bear"
    if _bearish(prev) and _bearish(last):
        return "two_bear"
    return None


def _anti_flat_ok(bars: list[Bar]) -> tuple[bool, dict]:
    atr = _atr_pct(bars, config.PAPER_VAC_ATR_PERIOD)
    rng = _range_pct(bars, config.PAPER_VAC_RANGE_BARS)
    ok_atr = atr is not None and atr >= config.PAPER_VAC_MIN_ATR_PCT
    ok_rng = rng is not None and rng >= config.PAPER_VAC_MIN_RANGE_PCT
    return ok_atr and ok_rng, {"atr_pct": atr, "range_20_pct": rng}


def _find_acb(
    closed: list[Bar],
    confirm_i: int,
    highs: list[dict],
    lows: list[dict],
) -> dict | None:
    wing = config.PAPER_VAC_SWING_CONFIRM
    min_swing = config.PAPER_VAC_MIN_SWING_PCT / 100.0
    min_ab = config.PAPER_VAC_MIN_AB_DIFF_PCT / 100.0
    max_after_b = config.PAPER_VAC_ENTRY_MAX_BARS_AFTER_B_CONFIRM
    min_after_b = config.PAPER_VAC_ENTRY_MIN_BARS_AFTER_B_CONFIRM
    promote_a = config.PAPER_VAC_PROMOTE_A_AFTER_BARS

    for b in reversed(highs):
        bi = int(b["bar_index"])
        bp = float(b["price"])
        if confirm_i < bi + wing:
            continue
        since_confirm = confirm_i - (bi + wing)
        if since_confirm < min_after_b or since_confirm > max_after_b:
            continue

        for a in reversed(highs):
            ai = int(a["bar_index"])
            ap = float(a["price"])
            if ai >= bi:
                continue
            if ap <= bp:
                continue
            if (ap - bp) / ap < min_ab:
                continue
            if confirm_i - ai > promote_a and bi - ai > promote_a:
                pass
            lows_between = [l for l in lows if ai < int(l["bar_index"]) < bi]
            if not lows_between:
                continue
            c = min(lows_between, key=lambda x: float(x["price"]))
            cp = float(c["price"])
            if (ap - cp) / ap < min_swing:
                continue
            if (bp - cp) / cp < min_swing:
                continue

            invalidated = False
            for j in range(bi + 1, confirm_i + 1):
                h = float(closed[j].high)
                if h > ap + 1e-12 or h > bp + 1e-12:
                    invalidated = True
                    break
            if invalidated:
                continue

            return {
                "a": a,
                "c": c,
                "b": b,
                "a_i": ai,
                "c_i": int(c["bar_index"]),
                "b_i": bi,
                "since_b_confirm": since_confirm,
            }
    return None


def evaluate_vac(state: SymbolState, now_ms: int) -> dict:
    bars = _bars5(state)
    closed = closed_bars(bars, "5", now_ms)
    lookback = config.PAPER_VAC_LOOKBACK_BARS
    if len(closed) > lookback:
        closed = closed[-lookback:]
    confirm_i = len(closed) - 1
    confirm = closed[confirm_i] if confirm_i >= 0 else None
    prev = closed[confirm_i - 1] if confirm_i >= 1 else None

    wing = config.PAPER_VAC_SWING_CONFIRM
    need = wing * 2 + 1 + config.PAPER_VAC_ATR_PERIOD + 5
    flat_ok, flat_m = _anti_flat_ok(closed) if len(closed) >= need else (False, {})
    highs = pivot_highs_indexed(closed, wing) if len(closed) >= wing * 2 + 1 else []
    lows = pivot_lows_indexed(closed, wing) if len(closed) >= wing * 2 + 1 else []

    struct = _find_acb(closed, confirm_i, highs, lows) if flat_ok and confirm and prev else None
    trigger = _entry_trigger(prev, confirm) if struct and prev and confirm else None

    swing_ok = struct is not None
    b_ok = swing_ok
    window_ok = (
        struct is not None
        and config.PAPER_VAC_ENTRY_MIN_BARS_AFTER_B_CONFIRM
        <= struct["since_b_confirm"]
        <= config.PAPER_VAC_ENTRY_MAX_BARS_AFTER_B_CONFIRM
    )
    inv_ok = swing_ok

    checks = {
        "anti_flat": _check(
            flat_ok,
            None if not flat_m else {k: _r(v, 3) if v is not None else None for k, v in flat_m.items()},
            f"ATR≥{config.PAPER_VAC_MIN_ATR_PCT}%, range≥{config.PAPER_VAC_MIN_RANGE_PCT}%",
        ),
        "structure_acb": _check(
            swing_ok,
            None
            if not struct
            else {
                "A": _r(float(struct["a"]["price"]), 6),
                "C": _r(float(struct["c"]["price"]), 6),
                "B": _r(float(struct["b"]["price"]), 6),
            },
            "A > B, C между",
        ),
        "b_confirmed": _check(
            b_ok,
            None if not struct else struct["since_b_confirm"],
            f"swing {wing}×{wing}",
        ),
        "entry_window": _check(
            window_ok,
            None if not struct else struct["since_b_confirm"],
            f"{config.PAPER_VAC_ENTRY_MIN_BARS_AFTER_B_CONFIRM}–{config.PAPER_VAC_ENTRY_MAX_BARS_AFTER_B_CONFIRM} баров",
        ),
        "entry_trigger": _check(
            trigger is not None,
            trigger,
            "pin+медвежья или 2×медвежья",
        ),
        "not_invalidated": _check(inv_ok, True if inv_ok else None, "нет пробоя A/B после B"),
    }

    failed = [k for k in VAC_MANDATORY if not checks[k]["ok"]]
    passed = not failed
    metrics: dict = {
        "confirm_ts": int(confirm.timestamp) if confirm else None,
        "bar_ts": int(confirm.timestamp) if confirm else None,
        "pump": {"kind": "vac", "side": "short", "trigger": "5m"},
    }
    if struct:
        metrics.update(
            {
                "a_ts": int(struct["a"]["time"]),
                "b_ts": int(struct["b"]["time"]),
                "c_ts": int(struct["c"]["time"]),
                "since_b_confirm": struct["since_b_confirm"],
                "entry_trigger": trigger,
            }
        )
        if flat_m:
            metrics["atr_pct"] = flat_m.get("atr_pct")
            metrics["range_20_pct"] = flat_m.get("range_20_pct")

    return {
        "checks": checks,
        "metrics": metrics,
        "score": 92.0 if passed else 28.0,
        "grade": grade_for(92.0 if passed else 28.0),
        "strict_btc": False,
        "passed": passed,
        "passed_count": len(VAC_MANDATORY) - len(failed),
        "failed": failed,
        "variants": [config.PAPER_VAC_VARIANT] if passed else [],
        "entry_blocked": [],
        "side": "short" if passed else None,
    }
