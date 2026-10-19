"""333: EMA20/EMA60 на 5m — в тренде только лонг или шорт; боковик по pivot (узкий range — отдельный фильтр)."""

from __future__ import annotations

import config
from signal_engine.indicators import ema
from signal_engine.paper.tight_chop import _closed_bars_before
from signal_engine.state import SymbolState

Regime = str  # "up" | "down" | "sideways"


def _closes(state: SymbolState, now_ms: int, interval: str) -> list[float]:
    raw = list(state.bars_htf.get(interval) or [])
    closed = _closed_bars_before(raw, now_ms)
    return [float(b.close) for b in closed]


def _slope_pct(now: float, prev: float) -> float:
    if prev <= 0:
        return 0.0
    return (now - prev) / prev * 100.0


def ma333_regime_detail(
    state: SymbolState,
    now_ms: int,
    side: str | None,
    interval: str = "5",
) -> dict:
    """
    EMA20 и EMA60 по закрытым барам interval.
    Тренд вниз/вверх — обе EMA с наклоном; иначе боковик.
    """
    fast = int(config.PAPER_333_MA_FAST)
    slow = int(config.PAPER_333_MA_SLOW)
    slope_bars = int(config.PAPER_333_MA_SLOPE_BARS)
    thr = float(config.PAPER_333_MA_SLOPE_MIN_PCT)
    min_closes = slow + slope_bars + 2

    closes = _closes(state, now_ms, interval)
    if len(closes) < min_closes:
        return {
            "insufficient_data": True,
            "ok": False,
            "regime": "unknown",
            "detail": f"мало баров {interval}m для EMA{slow} ({len(closes)}/{min_closes})",
        }

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    i = len(closes) - 1
    j = i - slope_bars
    v20 = ema_fast[i]
    v20_o = ema_fast[j]
    v60 = ema_slow[i]
    v60_o = ema_slow[j]
    if v20 is None or v20_o is None or v60 is None or v60_o is None:
        return {
            "insufficient_data": True,
            "ok": False,
            "regime": "unknown",
            "detail": "EMA не посчитаны",
        }

    s20 = _slope_pct(float(v20), float(v20_o))
    s60 = _slope_pct(float(v60), float(v60_o))
    if s20 <= -thr and s60 <= -thr:
        regime: Regime = "down"
    elif s20 >= thr and s60 >= thr:
        regime = "up"
    else:
        regime = "sideways"

    price = float(state.last_price or closes[-1])
    d20 = abs(price - float(v20))
    d60 = abs(price - float(v60))
    side_s = str(side or "").lower()

    ok = False
    detail = ""
    if regime == "down":
        ok = side_s == "short"
        detail = (
            f"EMA{fast}/EMA{slow} вниз (Δ{s20:+.2f}% / {s60:+.2f}% за {slope_bars} бар.) — только шорт"
            if ok
            else f"EMA вниз — лонг запрещён (Δ{s20:+.2f}% / {s60:+.2f}%)"
        )
    elif regime == "up":
        ok = side_s == "long"
        detail = (
            f"EMA{fast}/EMA{slow} вверх (Δ{s20:+.2f}% / {s60:+.2f}%) — только лонг"
            if ok
            else f"EMA вверх — шорт запрещён (Δ{s20:+.2f}% / {s60:+.2f}%)"
        )
    else:
        ok = True
        detail = f"боковик EMA (Δ{s20:+.2f}% / {s60:+.2f}%) — сторона по pivot, узкий range отдельно"

    return {
        "insufficient_data": False,
        "ok": ok,
        "regime": regime,
        "detail": detail,
        "ema20": round(float(v20), 8),
        "ema60": round(float(v60), 8),
        "slope_20_pct": round(s20, 4),
        "slope_60_pct": round(s60, 4),
        "dist_20": round(d20, 8),
        "dist_60": round(d60, 8),
        "price": round(price, 8),
        "side": side_s or None,
    }


def ma333_regime_allows(
    state: SymbolState,
    now_ms: int,
    side: str | None,
    interval: str = "5",
) -> tuple[bool, str, dict]:
    d = ma333_regime_detail(state, now_ms, side, interval)
    if d.get("insufficient_data"):
        d = {**d, "ok": True, "regime": "unknown", "detail": str(d.get("detail") or "мало баров — фильтр EMA пропущен")}
        return True, str(d["detail"]), d
    return bool(d.get("ok")), str(d.get("detail") or ""), d
