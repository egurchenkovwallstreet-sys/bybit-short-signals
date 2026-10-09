"""30 метрик × 3 горизонта для лаборатории пампа."""

from __future__ import annotations

import math
from typing import Any

import config
from signal_engine.flow import cvd_bearish, funding_extreme, oi_change_pct, taker_sellers_control
from signal_engine.indicators import sma
from signal_engine.liquidations import liquidations_faded, window_notionals
from signal_engine.levels import sweep_on_timeframe
from signal_engine.pump import price_change_pct
from signal_engine.state import SymbolState

MIN_MS = 60_000
HOUR_MS = 3_600_000

METRIC_GROUPS = (
    ("flow", "Поток сделок"),
    ("book", "Стакан"),
    ("leverage", "Плечо"),
    ("structure", "Структура"),
    ("market", "Рынок"),
)

METRIC_LABELS: dict[str, str] = {
    "delta": "Дельта (покупки − продажи)",
    "large_trades": "Крупные сделки",
    "absorption": "Поглощение",
    "tape_speed": "Скорость ленты",
    "buy_sell_imbalance": "Дисбаланс покупок/продаж",
    "wall_gone": "Стена в стакане",
    "spoof_risk": "Фейковые стены",
    "thin_book": "Тонкий стакан",
    "spread_volume": "Спред и объём",
    "liq_clusters": "Зоны ликвидности",
    "short_liq": "Ликвидации шортов",
    "long_liq": "Ликвидации лонгов",
    "liq_cascade": "Каскад ликвидаций",
    "funding_high": "Funding высокий",
    "funding_low": "Funding низкий",
    "price_up_oi_up": "Цена↑ OI↑",
    "price_up_oi_down": "Цена↑ OI↓",
    "price_down_oi_up": "Цена↓ OI↑",
    "price_down_oi_down": "Цена↓ OI↓",
    "oi_spike": "Скачок OI",
    "premium": "Премия фьюча",
    "crowd_skew": "Перекос толпы",
    "options_pain": "Опционы max pain",
    "breakout_vol": "Пробой без объёма",
    "sweep_reject": "Свип и возврат",
    "structure_lh": "Lower high / lower low",
    "cvd_div": "Дивергенция CVD",
    "btc_shift": "Разворот BTC",
    "beta_break": "Отрыв от BTC",
    "ema_break": "Пробой EMA",
}

HORIZON_LABELS = {"short": "Короткий", "mid": "Средний", "long": "Длинный"}

LOOKBACK_MIN = {"short": (5, 15, 30), "mid": (60, 240, 24 * 60), "long": (3 * 24 * 60, 7 * 24 * 60, 14 * 24 * 60)}


def _cell(value: float | None, signal: int = 0) -> dict[str, Any]:
    return {"value": round(value, 4) if value is not None and math.isfinite(value) else None, "signal": signal}


def _sum_window(bucket: dict[int, float], now_ms: int, minutes: int) -> float:
    start = now_ms - minutes * MIN_MS
    return sum(v for ts, v in bucket.items() if ts >= start)


def _cvd_window(state: SymbolState, now_ms: int, minutes: int) -> float:
    return _sum_window(state.cvd_delta, now_ms, minutes)


def _price_change(state: SymbolState, minutes: int) -> float | None:
    return price_change_pct(state.closes_1m(), minutes)


def _oi_change(state: SymbolState, minutes: int) -> float | None:
    return oi_change_pct(state.oi_points(), lookback_min=minutes)


def _liq_short_window(state: SymbolState, now_ms: int, minutes: int) -> float:
    vals = window_notionals(state.liq_notional, now_ms, minutes=minutes)
    return sum(vals) if vals else 0.0


def _liq_long_window(state: SymbolState, now_ms: int, minutes: int) -> float:
    current = (now_ms // MIN_MS) * MIN_MS
    start = current - (minutes - 1) * MIN_MS
    total = 0.0
    cursor = start
    while cursor <= current:
        total += float(state.liq_long_notional.get(cursor, 0.0))
        cursor += MIN_MS
    return total


def _horizon_metric(
    state: SymbolState,
    btc: SymbolState | None,
    now_ms: int,
    peak_price: float,
    horizon: str,
    idx: int,
) -> dict[str, Any]:
    minutes = LOOKBACK_MIN[horizon][idx]
    price_chg = _price_change(state, min(minutes, len(state.closes_1m()) - 1 or 1))
    oi_chg = _oi_change(state, min(minutes, 24 * 60))
    cvd = _cvd_window(state, now_ms, min(minutes, 180))
    buy = _sum_window(state.taker_buy, now_ms, min(minutes, 60))
    sell = _sum_window(state.taker_sell, now_ms, min(minutes, 60))
    total = buy + sell
    buy_share = (buy / total * 100.0) if total > 0 else None
    return {
        "minutes": minutes,
        "price_chg": price_chg,
        "oi_chg": oi_chg,
        "cvd": cvd,
        "buy_share": buy_share,
        "short_liq": _liq_short_window(state, now_ms, min(minutes, 60)),
        "long_liq": _liq_long_window(state, now_ms, min(minutes, 60)),
        "peak_price": peak_price,
    }


def compute_all_metrics(
    state: SymbolState,
    btc: SymbolState | None,
    peak_price: float,
    peak_ts: int,
    now_ms: int,
) -> dict[str, dict[str, dict[str, Any]]]:
    """30 ключей, у каждого short/mid/long."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    short = _horizon_metric(state, btc, now_ms, peak_price, "short", 1)
    mid = _horizon_metric(state, btc, now_ms, peak_price, "mid", 1)
    long = _horizon_metric(state, btc, now_ms, peak_price, "long", 1)

    def pack_delta(h: dict) -> dict[str, Any]:
        v = h.get("cvd")
        sig = -1 if v is not None and v < 0 else (1 if v and v > 0 else 0)
        return _cell(v, sig)

    out["delta"] = {"short": pack_delta(short), "mid": pack_delta(mid), "long": pack_delta(long)}

    closes = state.closes_1m()
    vols = state.volumes_1m()
    med = sma(vols[-30:-1], 20) if len(vols) > 25 else None
    large = 0.0
    for ts, val in state.taker_buy.items():
        if ts >= now_ms - 15 * MIN_MS and med and val > med * 3:
            large += val
    for ts, val in state.taker_sell.items():
        if ts >= now_ms - 15 * MIN_MS and med and val > med * 3:
            large += val
    out["large_trades"] = {
        "short": _cell(large, 1 if large > (med or 1) * 5 else 0),
        "mid": _cell(large * 2, 0),
        "long": _cell(large, 0),
    }

    absorp = None
    bs = short.get("buy_share")
    if short.get("price_chg") is not None and bs is not None:
        if abs(short["price_chg"]) < 1.0 and bs > 60:
            absorp = bs
    out["absorption"] = {"short": _cell(absorp, -1 if absorp else 0), "mid": _cell(None, 0), "long": _cell(None, 0)}

    tape_n = len([ts for ts in state.taker_buy if ts >= now_ms - 5 * MIN_MS]) + len(
        [ts for ts in state.taker_sell if ts >= now_ms - 5 * MIN_MS]
    )
    out["tape_speed"] = {
        "short": _cell(float(tape_n), 1 if tape_n > 20 else 0),
        "mid": _cell(float(tape_n), 0),
        "long": _cell(float(tape_n), 0),
    }

    def imb(h: dict) -> dict[str, Any]:
        bs = h.get("buy_share")
        if bs is None:
            return _cell(None, 0)
        return _cell(bs - 50.0, -1 if bs < 45 else (1 if bs > 55 else 0))

    out["buy_sell_imbalance"] = {"short": imb(short), "mid": imb(mid), "long": imb(long)}

    for key in ("wall_gone", "spoof_risk", "thin_book", "spread_volume", "liq_clusters", "crowd_skew", "options_pain"):
        out[key] = {"short": _cell(None, 0), "mid": _cell(None, 0), "long": _cell(None, 0)}

    def liq_fade_short(minutes: int) -> dict[str, Any]:
        vals = window_notionals(state.liq_notional, now_ms, minutes=min(minutes, 15))
        faded = liquidations_faded(vals, config.PAPER_SHORT_LIQ_FADE_MIN) if vals else False
        peak = max(vals) if vals else 0.0
        cur = vals[-1] if vals else 0.0
        ratio = (1.0 - cur / peak) if peak > 0 else None
        return _cell(ratio, -1 if faded else 0)

    out["short_liq"] = {
        "short": liq_fade_short(15),
        "mid": liq_fade_short(60),
        "long": liq_fade_short(240),
    }
    out["long_liq"] = {
        "short": _cell(short.get("long_liq"), 1 if (short.get("long_liq") or 0) > 1000 else 0),
        "mid": _cell(mid.get("long_liq"), 0),
        "long": _cell(long.get("long_liq"), 0),
    }
    cascade = max(window_notionals(state.liq_notional, now_ms, minutes=5) or [0.0])
    out["liq_cascade"] = {"short": _cell(cascade, 1 if cascade > 50000 else 0), "mid": _cell(None, 0), "long": _cell(None, 0)}

    fr = state.funding_rate
    out["funding_high"] = {
        "short": _cell(fr * 100 if fr is not None else None, -1 if funding_extreme(fr) and (fr or 0) > 0 else 0),
        "mid": _cell(fr * 100 if fr is not None else None, 0),
        "long": _cell(fr * 100 if fr is not None else None, 0),
    }
    out["funding_low"] = {
        "short": _cell(fr * 100 if fr is not None else None, 1 if fr is not None and fr < -0.0003 else 0),
        "mid": _cell(None, 0),
        "long": _cell(None, 0),
    }

    def oi_combo(h: dict, up_price: bool) -> dict[str, Any]:
        pc = h.get("price_chg")
        oc = h.get("oi_chg")
        if pc is None or oc is None:
            return _cell(None, 0)
        if up_price and pc > 0 and oc > 0:
            return _cell(oc, 1)
        if up_price and pc > 0 and oc < 0:
            return _cell(oc, -1)
        if not up_price and pc < 0 and oc > 0:
            return _cell(oc, 1)
        if not up_price and pc < 0 and oc < 0:
            return _cell(oc, -1)
        return _cell(oc, 0)

    out["price_up_oi_up"] = {"short": oi_combo(short, True), "mid": oi_combo(mid, True), "long": oi_combo(long, True)}
    out["price_up_oi_down"] = {
        "short": oi_combo(short, True) if (short.get("price_chg") or 0) > 0 and (short.get("oi_chg") or 0) < 0 else _cell(short.get("oi_chg"), -1),
        "mid": oi_combo(mid, True),
        "long": oi_combo(long, True),
    }
    out["price_down_oi_up"] = {"short": oi_combo(short, False), "mid": oi_combo(mid, False), "long": oi_combo(long, False)}
    out["price_down_oi_down"] = {"short": oi_combo(short, False), "mid": oi_combo(mid, False), "long": oi_combo(long, False)}

    oi_sp = short.get("oi_chg")
    out["oi_spike"] = {"short": _cell(oi_sp, 1 if oi_sp is not None and abs(oi_sp) > 3 else 0), "mid": _cell(mid.get("oi_chg"), 0), "long": _cell(long.get("oi_chg"), 0)}

    out["premium"] = {"short": _cell(None, 0), "mid": _cell(None, 0), "long": _cell(None, 0)}

    vol_ratio = None
    if len(vols) > 25:
        base = sma(vols[-21:-1], 20)
        if base and base > 0:
            vol_ratio = vols[-1] / base
    brk = short.get("price_chg")
    out["breakout_vol"] = {
        "short": _cell(vol_ratio, -1 if brk and brk > 2 and vol_ratio and vol_ratio < 2 else 0),
        "mid": _cell(vol_ratio, 0),
        "long": _cell(vol_ratio, 0),
    }

    swept = False
    for interval, ms in (("60", HOUR_MS), ("240", 4 * HOUR_MS)):
        candles = state.htf_candles(interval)
        if candles:
            ok, _, _ = sweep_on_timeframe(candles, now_ms, ms)
            swept = swept or ok
    out["sweep_reject"] = {"short": _cell(1.0 if swept else 0.0, -1 if swept else 0), "mid": _cell(None, 0), "long": _cell(None, 0)}

    lh = 1.0 if (short.get("price_chg") or 0) < -1 else 0.0
    out["structure_lh"] = {"short": _cell(lh, -1 if lh else 0), "mid": _cell(lh, 0), "long": _cell(lh, 0)}

    bear = cvd_bearish(state.cvd_delta, short.get("price_chg") or 0, now_ms)
    out["cvd_div"] = {"short": _cell(1.0 if bear else 0.0, -1 if bear else 0), "mid": _cell(None, 0), "long": _cell(None, 0)}

    btc_chg = _price_change(btc, 240) if btc else None
    out["btc_shift"] = {
        "short": _cell(btc_chg, -1 if btc_chg is not None and btc_chg <= -3 else 0),
        "mid": _cell(btc_chg, 0),
        "long": _cell(btc_chg, 0),
    }

    alt = short.get("price_chg")
    out["beta_break"] = {
        "short": _cell((alt or 0) - (btc_chg or 0) if alt is not None and btc_chg is not None else None, 0),
        "mid": _cell(None, 0),
        "long": _cell(None, 0),
    }

    from signal_engine.flow import taker_ratio

    ratio = taker_ratio(state.taker_buy, state.taker_sell, now_ms)
    sellers = taker_sellers_control(ratio)
    out["ema_break"] = {"short": _cell(1.0 if sellers else 0.0, -1 if sellers else 0), "mid": _cell(None, 0), "long": _cell(None, 0)}

    return out


def metrics_summary(metrics: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    bearish = 0
    bullish = 0
    filled = 0
    for horizons in metrics.values():
        for cell in horizons.values():
            if cell.get("value") is not None:
                filled += 1
            sig = cell.get("signal") or 0
            if sig < 0:
                bearish += 1
            elif sig > 0:
                bullish += 1
    return {"bearish": bearish, "bullish": bullish, "filled": filled, "total_cells": len(METRIC_LABELS) * 3}
