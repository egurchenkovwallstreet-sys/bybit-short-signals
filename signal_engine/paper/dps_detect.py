"""Дип сик: вход по блокам DeepSeek (упрощения где нет данных), выход как t20 в strategy."""

from __future__ import annotations

import config
from signal_engine.flow import oi_change_pct
from signal_engine.indicators import rsi, sma
from signal_engine.paper.detect import MIN_MS, _check, _r, grade_for
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState

DPS_MANDATORY = (
    "trigger_4h_24h",
    "rsi_5m_cross",
    "rsi_1h_hot",
    "rsi_15m_floor",
    "cvd_divergence",
    "cvd_slope",
    "delta_now",
    "delta_3",
    "oi_24h",
    "oi_1h",
    "funding_hot",
    "book_imbalance",
    "book_ask_bid",
    "volume_fade",
    "volume_spike_pump",
    "drop_from_4h_high",
    "below_vwap_4h",
    "liq_zone",
    "turnover_ok",
    "funding_not_short_crowded",
)

DPS_CHECK_LABELS = {
    "trigger_4h_24h": "Памп 4ч/24ч (пороги мини-тест 2)",
    "rsi_5m_cross": "RSI(7) 5m: пересечение 70 сверху вниз",
    "rsi_1h_hot": "RSI(7) 1h ≥ 70",
    "rsi_15m_floor": "RSI(7) 15m ≥ 35",
    "cvd_divergence": "Медвежья дивергенция CVD (20×5m)",
    "cvd_slope": "Крупный поток / CVD: наклон вниз (5×5m)",
    "delta_now": "Delta текущей 5m < 0",
    "delta_3": "Сумма Delta 3×5m < 0",
    "oi_24h": "OI +5% за 24ч (или доступное окно)",
    "oi_1h": "OI +2% за 1ч",
    "funding_hot": "Funding ≥ 0.1% (8ч экв.)",
    "book_imbalance": "Imbalance стакана < −0.2 (топ‑20 или ±1%)",
    "book_ask_bid": "Ask/Bid по объёму ≥ 1.5",
    "volume_fade": "Объём 5m ≤ 50% среднего за 20",
    "volume_spike_pump": "На пампе был всплеск объёма ≥ 2×",
    "drop_from_4h_high": "Цена ≥ 8% ниже 4h максимума",
    "below_vwap_4h": "Цена ниже VWAP 4ч",
    "liq_zone": "Зона ликв. лонгов (~5–10% под пиком + OI↑)",
    "turnover_ok": "Оборот 24ч ≥ $10M",
    "funding_not_short_crowded": "Funding не отрицательный",
}


def _closed_5m(state: SymbolState, now_ms: int) -> list[Bar]:
    step = 5 * MIN_MS
    grouped: dict[int, list[Bar]] = {}
    for bar in state.bars_1m:
        key = (int(bar.timestamp) // step) * step
        grouped.setdefault(key, []).append(bar)
    out: list[Bar] = []
    for key in sorted(grouped):
        if key + step > now_ms:
            continue
        rows = sorted(grouped[key], key=lambda b: b.timestamp)
        if len(rows) < 5:
            continue
        out.append(
            Bar(
                key,
                rows[0].open,
                max(r.high for r in rows),
                min(r.low for r in rows),
                rows[-1].close,
                sum(r.volume for r in rows),
            )
        )
    return out


def _htf_closes(state: SymbolState, interval: str, now_ms: int) -> list[float]:
    step = {"15": 15 * MIN_MS, "60": 60 * MIN_MS}.get(interval, 60 * MIN_MS)
    bars = state.bars_htf.get(interval) or []
    closed = [b for b in bars if b.timestamp + step <= now_ms]
    if not closed and len(bars) > 1:
        closed = bars[:-1]
    return [float(b.close) for b in closed]


def _bar_deltas(state: SymbolState, bars: list[Bar]) -> list[float]:
    out: list[float] = []
    for bar in bars:
        buy = sell = 0.0
        end = bar.timestamp + 5 * MIN_MS
        cursor = bar.timestamp
        while cursor < end:
            buy += float(state.taker_buy.get(cursor, 0.0))
            sell += float(state.taker_sell.get(cursor, 0.0))
            cursor += MIN_MS
        out.append(buy - sell)
    return out


def _cvd_divergence_20(bars: list[Bar], deltas: list[float]) -> tuple[bool | None, dict]:
    if len(bars) < 20 or len(deltas) < 20:
        return None, {}
    window_b = bars[-20:]
    window_d = deltas[-20:]
    highs = [b.high for b in window_b]
    max_h = max(highs)
    peak_i = len(highs) - 1 - highs[::-1].index(max_h)
    if peak_i < len(highs) - 3:
        return False, {"peak_age_bars": len(highs) - 1 - peak_i}
    cum: list[float] = []
    s = 0.0
    for d in window_d:
        s += d
        cum.append(s)
    prev_cvd_max = max(cum[:peak_i]) if peak_i > 0 else cum[0]
    ok = cum[peak_i] < prev_cvd_max - 1e-9
    return ok, {"peak_high": _r(max_h, 6), "cvd_at_peak": _r(cum[peak_i], 0), "prev_cvd_max": _r(prev_cvd_max, 0)}


def _large_flow_slope(deltas: list[float]) -> tuple[bool | None, float | None]:
    """Прокси «институционального» CVD: наклон суммы delta за 5 последних 5m."""
    if len(deltas) < 5:
        return None, None
    tail = deltas[-5:]
    slope = tail[-1] - tail[0]
    return slope < 0, slope


def _book_top20(state: SymbolState) -> tuple[float | None, float | None]:
    last = float(state.last_price or 0)
    if last <= 0:
        return None, None
    bids = sorted(((p, s) for p, s in state.book_bids.items() if s > 0), reverse=True)[:20]
    asks = sorted(((p, s) for p, s in state.book_asks.items() if s > 0))[:20]
    if not bids and not asks:
        from signal_engine.paper.css2_detect import book_imbalance_1pct

        imb = book_imbalance_1pct(state)
        if imb is None:
            return None, None
        lo, hi = last * 0.99, last * 1.01
        bid = sum(px * sz for px, sz in state.book_bids.items() if lo <= px <= last)
        ask = sum(px * sz for px, sz in state.book_asks.items() if last <= px <= hi)
        ratio = (ask / bid) if bid > 0 else None
        return imb, ratio
    bid_usd = sum(p * s for p, s in bids)
    ask_usd = sum(p * s for p, s in asks)
    if bid_usd + ask_usd <= 0:
        return None, None
    imb = (bid_usd - ask_usd) / (bid_usd + ask_usd)
    ratio = ask_usd / bid_usd if bid_usd > 0 else None
    return imb, ratio


def _vwap_4h(state: SymbolState, now_ms: int) -> float | None:
    start = now_ms - 4 * 60 * MIN_MS
    num = den = 0.0
    for bar in state.bars_1m:
        if bar.timestamp < start or bar.timestamp > now_ms:
            continue
        num += bar.close * bar.volume
        den += bar.volume
    return num / den if den > 0 else None


def _high_4h(state: SymbolState, now_ms: int) -> float | None:
    start = now_ms - 4 * 60 * MIN_MS
    highs = [b.high for b in state.bars_1m if start <= b.timestamp <= now_ms]
    return max(highs) if highs else None


def _check_soft(ok: bool | None, value, need: str) -> dict:
    if ok is None:
        return {"ok": True, "value": "нет данных — не блокируем", "need": need, "skipped": True}
    return {"ok": bool(ok), "value": value, "need": need}


def evaluate_dps(
    state: SymbolState,
    tape: SymbolTape | None,
    pump,
    now_ms: int,
    score: float,
    strict_btc: bool,
) -> dict:
    pump_data = pump.to_data() if hasattr(pump, "to_data") else (pump or {})
    trigger = str(pump_data.get("trigger") or getattr(pump, "trigger", "") or "")

    bars5 = _closed_5m(state, now_ms)
    deltas = _bar_deltas(state, bars5)
    closes5 = [b.close for b in bars5]

    r5_prev = rsi(closes5[:-1], config.PAPER_DPS_RSI_PERIOD) if len(closes5) > 8 else None
    r5 = rsi(closes5, config.PAPER_DPS_RSI_PERIOD) if len(closes5) > 7 else None
    cross = (
        r5_prev is not None
        and r5 is not None
        and r5_prev >= config.PAPER_DPS_RSI_CROSS
        and r5 < config.PAPER_DPS_RSI_CROSS
    )

    c1h = _htf_closes(state, "60", now_ms)
    c15 = _htf_closes(state, "15", now_ms)
    r1h = rsi(c1h, config.PAPER_DPS_RSI_PERIOD) if len(c1h) > 8 else None
    r15 = rsi(c15, config.PAPER_DPS_RSI_PERIOD) if len(c15) > 8 else None

    div_ok, div_meta = _cvd_divergence_20(bars5, deltas)
    slope_ok, slope = _large_flow_slope(deltas)
    d_now = deltas[-1] if deltas else None
    d3 = sum(deltas[-3:]) if len(deltas) >= 3 else None

    points = state.oi_points()
    oi24 = oi_change_pct(points, 24 * 60)
    oi1 = oi_change_pct(points, 60)
    if oi24 is None and len(points) >= 2:
        oi24 = oi_change_pct(points, max(60, (points[-1][0] - points[0][0]) // 60_000))

    fr = state.funding_rate
    imb, ask_bid = _book_top20(state)

    vol_ok = None
    vol_spike = None
    if len(bars5) >= 21:
        closed_v = [b.volume for b in bars5]
        avg20 = sma(closed_v[:-1], 20)
        last_v = closed_v[-1]
        if avg20 and avg20 > 0:
            vol_ok = last_v <= avg20 * config.PAPER_DPS_VOL_FADE_RATIO
            peak_v = max(closed_v[-40:])
            vol_spike = peak_v >= avg20 * config.PAPER_DPS_VOL_SPIKE_MIN

    hi4 = _high_4h(state, now_ms)
    last = float(state.last_price or 0)
    drop_ok = None
    if hi4 and hi4 > 0 and last > 0:
        drop_ok = last <= hi4 * (1 - config.PAPER_DPS_DROP_FROM_4H_HIGH_PCT / 100.0)

    vwap = _vwap_4h(state, now_ms)
    below_vwap = vwap is not None and last > 0 and last < vwap

    peak_p = float(getattr(pump, "peak_price", 0) or pump_data.get("peak_price") or 0)
    liq_zone = None
    if peak_p > 0 and last > 0:
        pct = (peak_p - last) / peak_p * 100.0
        oi_up = oi1 is not None and oi1 >= config.PAPER_DPS_OI_1H_MIN
        liq_zone = (
            config.PAPER_DPS_LIQ_ZONE_MIN_PCT <= pct <= config.PAPER_DPS_LIQ_ZONE_MAX_PCT
            and (oi_up if oi1 is not None else True)
        )

    turnover = state.turnover_24h_usdt

    checks = {
        "trigger_4h_24h": _check(trigger in config.PAPER_MINI_TRIGGERS, trigger or "нет", "4h или 24h"),
        "rsi_5m_cross": _check_soft(
            cross if r5 is not None else None,
            None if r5 is None else {"prev": _r(r5_prev, 1), "now": _r(r5, 1)},
            f"пересечение {config.PAPER_DPS_RSI_CROSS:g} вниз",
        ),
        "rsi_1h_hot": _check_soft(
            r1h >= config.PAPER_DPS_RSI_1H_MIN if r1h is not None else None,
            None if r1h is None else _r(r1h, 1),
            f"≥ {config.PAPER_DPS_RSI_1H_MIN:g}",
        ),
        "rsi_15m_floor": _check_soft(
            r15 >= config.PAPER_DPS_RSI_15M_MIN if r15 is not None else None,
            None if r15 is None else _r(r15, 1),
            f"≥ {config.PAPER_DPS_RSI_15M_MIN:g}",
        ),
        "cvd_divergence": _check_soft(div_ok, div_meta or {}, "цена↑ CVD нет"),
        "cvd_slope": _check_soft(slope_ok, None if slope is None else _r(slope, 0), "наклон < 0"),
        "delta_now": _check_soft(d_now < 0 if d_now is not None else None, d_now, "< 0"),
        "delta_3": _check_soft(d3 < 0 if d3 is not None else None, d3, "сумма < 0"),
        "oi_24h": _check_soft(
            oi24 >= config.PAPER_DPS_OI_24H_MIN if oi24 is not None else None,
            oi24,
            f"≥ {config.PAPER_DPS_OI_24H_MIN:g}%",
        ),
        "oi_1h": _check_soft(
            oi1 >= config.PAPER_DPS_OI_1H_MIN if oi1 is not None else None,
            oi1,
            f"≥ {config.PAPER_DPS_OI_1H_MIN:g}%",
        ),
        "funding_hot": _check_soft(
            fr >= config.PAPER_DPS_FUNDING_MIN if fr is not None else None,
            fr,
            f"≥ {config.PAPER_DPS_FUNDING_MIN * 100:g}%",
        ),
        "book_imbalance": _check_soft(
            imb < config.PAPER_DPS_BOOK_IMBALANCE_MAX if imb is not None else None,
            imb,
            f"< {config.PAPER_DPS_BOOK_IMBALANCE_MAX:g}",
        ),
        "book_ask_bid": _check_soft(
            ask_bid >= config.PAPER_DPS_ASK_BID_MIN if ask_bid is not None else None,
            ask_bid,
            f"≥ {config.PAPER_DPS_ASK_BID_MIN:g}",
        ),
        "volume_fade": _check_soft(vol_ok, vol_ok, "≤ 50% avg20"),
        "volume_spike_pump": _check_soft(vol_spike, vol_spike, f"≥ {config.PAPER_DPS_VOL_SPIKE_MIN:g}×"),
        "drop_from_4h_high": _check_soft(drop_ok, drop_ok, f"−{config.PAPER_DPS_DROP_FROM_4H_HIGH_PCT:g}% от 4h high"),
        "below_vwap_4h": _check_soft(below_vwap if vwap else None, below_vwap, "< VWAP 4h"),
        "liq_zone": _check_soft(liq_zone, liq_zone, "5–10% под пиком"),
        "turnover_ok": _check_soft(
            turnover >= config.PAPER_DPS_MIN_TURNOVER if turnover is not None else None,
            turnover,
            f"≥ ${config.PAPER_DPS_MIN_TURNOVER // 1_000_000}M",
        ),
        "funding_not_short_crowded": _check_soft(
            fr >= 0 if fr is not None else None,
            fr,
            "≥ 0",
        ),
    }
    failed = [k for k in DPS_MANDATORY if not checks[k]["ok"]]
    passed = not failed
    return {
        "checks": checks,
        "metrics": {
            "pump": pump_data,
            "bars_5m": len(bars5),
            "tape": tape is not None,
        },
        "score": round(score, 1),
        "grade": grade_for(score),
        "strict_btc": strict_btc,
        "passed": passed,
        "passed_count": len(DPS_MANDATORY) - len(failed),
        "failed": failed,
        "variants": [config.PAPER_DPS_VARIANT] if passed else [],
        "entry_blocked": [],
    }
