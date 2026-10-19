"""333: EMA60 — тренд по наклону; боковик не торгуем; полоса ±1% у EMA; stretch >4%."""

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


def _band_frac() -> float:
    return float(config.PAPER_333_MA_BAND_PCT) / 100.0


def _stretch_frac() -> float:
    return float(config.PAPER_333_MA_STRETCH_PCT) / 100.0


def ma333_price_entry_ok(
    regime: Regime,
    side: str,
    price: float,
    ema60: float,
) -> tuple[bool, str, str | None]:
    """
    Лонг: EMA↑ и EMA…EMA+1%; или EMA↓ и price < EMA−4%.
    Шорт: EMA↓ и EMA−1%…EMA; или EMA↑ и price > EMA+4%.
    Между 1% и 4% от EMA — мёртвая зона.
    """
    band = _band_frac()
    stretch = _stretch_frac()
    e = float(ema60)
    side_s = str(side or "").lower()
    p = float(price)
    bp = band * 100.0
    sp = stretch * 100.0

    if side_s == "long":
        if regime == "up":
            if p + 1e-12 < e:
                return False, f"лонг: цена {p:.8g} ниже EMA60 {e:.8g}", None
            if p > e * (1 + band) + 1e-12:
                return False, f"лонг: цена выше EMA60+{bp:g}%", None
            return True, f"лонг: EMA60 … EMA60+{bp:g}%", "base"
        if regime == "down":
            if p >= e * (1 - stretch) - 1e-12:
                if p >= e - 1e-12:
                    return False, "лонг при EMA↓: цена не ниже EMA60", None
                return False, f"лонг: мёртвая зона {bp:g}–{sp:g}% ниже EMA60", None
            return True, f"лонг: отрыв >{sp:g}% ниже EMA60 при EMA↓", "stretch"
    elif side_s == "short":
        if regime == "down":
            if p > e + 1e-12:
                return False, f"шорт: цена {p:.8g} выше EMA60 {e:.8g}", None
            if p + 1e-12 < e * (1 - band):
                return False, f"шорт: цена ниже EMA60−{bp:g}%", None
            return True, f"шорт: EMA60−{bp:g}% … EMA60", "base"
        if regime == "up":
            if p <= e * (1 + stretch) + 1e-12:
                if p <= e + 1e-12:
                    return False, "шорт при EMA↑: цена не выше EMA60", None
                return False, f"шорт: мёртвая зона {bp:g}–{sp:g}% выше EMA60", None
            return True, f"шорт: отрыв >{sp:g}% выше EMA60 при EMA↑", "stretch"

    return False, "—", None


def ma333_regime_detail(
    state: SymbolState,
    now_ms: int,
    side: str | None,
    interval: str = "5",
) -> dict:
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
    entry_zone: str | None = None
    if regime == "sideways":
        detail = f"боковик EMA60 (Δ{s60:+.2f}% за {slope_bars} бар.) — вход запрещён"
    elif side_s not in ("long", "short"):
        detail = "нет стороны сделки"
    else:
        ok, detail, entry_zone = ma333_price_entry_ok(regime, side_s, price, ema60)

    return {
        "insufficient_data": False,
        "ok": ok,
        "regime": regime,
        "detail": detail,
        "entry_zone": entry_zone,
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
