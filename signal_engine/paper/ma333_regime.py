"""333: только EMA60 на 5m — тренд по наклону; боковик не торгуем; цена vs EMA60."""

from __future__ import annotations

import config
from signal_engine.indicators import ema
from signal_engine.state import SymbolState
from signal_engine.swing_highs import closed_bars

Regime = str  # "up" | "down" | "sideways"


def _closes(state: SymbolState, now_ms: int, interval: str) -> list[float]:
    raw = list(state.bars_htf.get(interval) or [])
    closed = closed_bars(raw, interval, now_ms)
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
    EMA60 по закрытым барам interval.
    Наклон — изменение за PAPER_333_MA_SLOPE_BARS свечей.
    Боковик: вход запрещён. Тренд вниз — только шорт и price ≤ EMA60; вверх — лонг и price ≥ EMA60.
    """
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

    ema_slow = ema(closes, slow)
    i = len(closes) - 1
    j = i - slope_bars
    v60 = ema_slow[i]
    v60_o = ema_slow[j]
    if v60 is None or v60_o is None:
        return {
            "insufficient_data": True,
            "ok": False,
            "regime": "unknown",
            "detail": "EMA60 не посчитана",
        }

    s60 = _slope_pct(float(v60), float(v60_o))
    if s60 <= -thr:
        regime: Regime = "down"
    elif s60 >= thr:
        regime = "up"
    else:
        regime = "sideways"

    price = float(state.last_price or closes[-1])
    side_s = str(side or "").lower()
    ema60 = float(v60)

    ok = False
    detail = ""
    if regime == "sideways":
        detail = f"боковик EMA60 (Δ{s60:+.2f}% за {slope_bars} бар.) — вход запрещён"
    elif regime == "down":
        if side_s != "short":
            detail = f"EMA60 вниз (Δ{s60:+.2f}%) — лонг запрещён"
        elif price > ema60 + 1e-12:
            detail = f"шорт: цена {price:.8g} выше EMA60 {ema60:.8g}"
        else:
            ok = True
            detail = f"EMA60 вниз, цена ≤ EMA60 — шорт"
    elif regime == "up":
        if side_s != "long":
            detail = f"EMA60 вверх (Δ{s60:+.2f}%) — шорт запрещён"
        elif price + 1e-12 < ema60:
            detail = f"лонг: цена {price:.8g} ниже EMA60 {ema60:.8g}"
        else:
            ok = True
            detail = f"EMA60 вверх, цена ≥ EMA60 — лонг"

    return {
        "insufficient_data": False,
        "ok": ok,
        "regime": regime,
        "detail": detail,
        "ema60": round(ema60, 8),
        "slope_60_pct": round(s60, 4),
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
        return False, str(d.get("detail") or "мало баров — вход запрещён"), d
    return bool(d.get("ok")), str(d.get("detail") or ""), d
