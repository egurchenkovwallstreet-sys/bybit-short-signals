"""Детектор роста и условия входа в бумажный лонг (вариант lt20)."""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.flow import oi_change_pct
from signal_engine.paper.detect import HOUR_MS, _r, _check, ema_table, grade_for
from signal_engine.paper.swing_1h import (
    analyze_growth_swing_1h,
    pullback_entry_ok,
    pullback_pct_from_peak,
)
from signal_engine.swing_highs import closed_bars
from signal_engine.paper.tape import SymbolTape
from signal_engine.state import Bar, SymbolState

GROWTH_CORE = (
    "hh_structure_12h",
    "pullback_entry",
    "ema_above",
)
GROWTH_FLEX = (
    "oi_1h_up",
    "oi_4h_up",
    "buys_rising_1h",
    "buy_share_60",
    "volume_up_1h",
    "volume_up_4h",
    "volume_avg_4h",
    "hh_hl_1h",
)
GROWTH_MANDATORY = GROWTH_CORE + GROWTH_FLEX

GROWTH_CHECK_LABELS = {
    "oi_1h_up": "OI ↑ за 1 ч",
    "oi_4h_up": "OI ↑ за 4 ч",
    "buys_rising_1h": "Покупки растут за 1 ч",
    "buy_share_60": f"Покупки > {config.PAPER_GROWTH_BUY_SHARE_MIN:g}%",
    "volume_up_1h": f"Объём ↑ за 1 ч ≥ {config.PAPER_GROWTH_VOL_GROWTH_MIN_PCT:g}%",
    "volume_up_4h": f"Объём ↑ за 4 ч ≥ {config.PAPER_GROWTH_VOL_GROWTH_MIN_PCT:g}%",
    "volume_avg_4h": f"Средний рост объёма за 4 ч ≥ {config.PAPER_GROWTH_VOL_GROWTH_MIN_PCT:g}%/ч",
    "ema_above": "Цена выше EMA50 на 15m и 1H",
    "hh_hl_1h": "1H: high и low выше предыдущих",
    "hh_structure_12h": "Структура HH за 12 ч (1H swing)",
    "pullback_entry": (
        f"Откат {config.PAPER_GROWTH_PULLBACK_MIN_PCT:g}–"
        f"{config.PAPER_GROWTH_PULLBACK_MAX_PCT:g}% от HH 1H"
    ),
    "turbo_vol_x3": f"Турбо: объём ×{config.PAPER_GROWTH_TURBO_VOL_RATIO:g} за 4 ч",
    "turbo_buys_75": f"Турбо: покупки ≥ {config.PAPER_GROWTH_BUY_SHARE_TURBO:g}%",
}


@dataclass
class GrowthInfo:
    anchor_price: float
    anchor_ts: int
    rally_pct: float
    peak_price: float
    peak_ts: int
    volume_ratio_4h: float | None = None
    buy_share_pct: float | None = None

    def to_data(self) -> dict:
        return {
            "kind": "growth",
            "anchor_price": self.anchor_price,
            "anchor_ts": self.anchor_ts,
            "rally_pct": _r(self.rally_pct, 2),
            "peak_price": self.peak_price,
            "peak_ts": self.peak_ts,
            "volume_ratio_4h": _r(self.volume_ratio_4h, 2),
            "buy_share_pct": _r(self.buy_share_pct, 1),
        }


@dataclass
class GrowthEvaluation:
    checks: dict[str, dict]
    metrics: dict
    score: float
    turbo: bool

    @property
    def ema_ok(self) -> bool:
        return bool(self.checks.get("ema_above", {}).get("ok"))

    @property
    def structure_ok(self) -> bool:
        return bool(self.checks.get("hh_structure_12h", {}).get("ok"))

    @property
    def pullback_ok(self) -> bool:
        return bool(self.checks.get("pullback_entry", {}).get("ok"))

    @property
    def flex_passed(self) -> int:
        return sum(1 for k in GROWTH_FLEX if self.checks.get(k, {}).get("ok"))

    @property
    def passed(self) -> bool:
        if not self.ema_ok or not self.structure_ok or not self.pullback_ok:
            return False
        if self.turbo:
            return True
        return self.flex_passed >= config.PAPER_GROWTH_FLEX_MIN

    @property
    def failed(self) -> list[str]:
        out: list[str] = []
        if not self.ema_ok:
            out.append("ema_above")
        if not self.structure_ok:
            out.append("hh_structure_12h")
        if not self.pullback_ok:
            out.append("pullback_entry")
        if self.turbo:
            return out
        if self.flex_passed < config.PAPER_GROWTH_FLEX_MIN:
            for k in GROWTH_FLEX:
                if not self.checks.get(k, {}).get("ok") and k not in out:
                    out.append(k)
        return out

    @property
    def passed_count(self) -> int:
        return sum(1 for k in GROWTH_MANDATORY if self.checks.get(k, {}).get("ok"))

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
            "variants": [config.PAPER_LT20_VARIANT] if self.passed else [],
            "entry_blocked": [],
            "turbo": self.turbo,
        }


def _hourly_volumes(bars_1m: list[Bar], now_ms: int, hours: int) -> list[float]:
    out: list[float] = []
    for h in range(hours):
        end = now_ms - h * HOUR_MS
        start = end - HOUR_MS
        vol = sum(b.volume for b in bars_1m if start <= b.timestamp < end)
        out.append(vol)
    return list(reversed(out))


def _volume_growth_pct(recent: float, prior: float) -> float | None:
    if prior <= 0:
        return None
    return (recent / prior - 1.0) * 100.0


def _avg_hourly_growth_pct(hourly: list[float]) -> float | None:
    """Средний % прироста объёма час к часу (последние len(hourly)-1 шагов)."""
    if len(hourly) < 2:
        return None
    steps: list[float] = []
    for i in range(1, len(hourly)):
        if hourly[i - 1] <= 0:
            continue
        steps.append((hourly[i] / hourly[i - 1] - 1.0) * 100.0)
    if not steps:
        return None
    return sum(steps) / len(steps)


def find_growth(
    state: SymbolState,
    tape: SymbolTape | None,
    now_ms: int,
    klines: dict[str, list[Bar]] | None = None,
) -> GrowthInfo | None:
    """Эпизод роста: HH-структура 1H за 12 ч, пик/якорь по swing 1H."""
    klines = klines or {}
    last = float(state.last_price or 0)
    if last <= 0:
        return None

    struct = analyze_growth_swing_1h(klines.get("60") or [], now_ms, last)
    if not struct.valid:
        return None

    anchor = struct.anchor_price
    peak = struct.peak_price
    if anchor <= 0 or peak <= 0 or last <= anchor:
        return None
    rally = (last / anchor - 1.0) * 100.0
    if rally < config.PAPER_GROWTH_MIN_RALLY_PCT:
        return None

    vol_4h = sum(b.volume for b in state.bars_1m if b.timestamp >= now_ms - 4 * HOUR_MS)
    vol_prev = sum(
        b.volume for b in state.bars_1m if now_ms - 8 * HOUR_MS <= b.timestamp < now_ms - 4 * HOUR_MS
    )
    vol_ratio = vol_4h / vol_prev if vol_prev > 0 else None

    buy_share = None
    if tape is not None:
        b, s = tape.minute_window(now_ms, 60)
        tot = b + s
        buy_share = b / tot * 100.0 if tot > 0 else None

    return GrowthInfo(
        anchor_price=anchor,
        anchor_ts=struct.anchor_ts,
        rally_pct=rally,
        peak_price=peak,
        peak_ts=struct.peak_ts,
        volume_ratio_4h=vol_ratio,
        buy_share_pct=buy_share,
    )


def refresh_growth_peak(
    growth: GrowthInfo,
    state: SymbolState,
    now_ms: int,
    klines: dict[str, list[Bar]] | None = None,
) -> bool:
    klines = klines or {}
    last = float(state.last_price or growth.peak_price)
    struct = analyze_growth_swing_1h(klines.get("60") or [], now_ms, last)
    if not struct.valid:
        return False
    changed = False
    if struct.peak_price > growth.peak_price + 1e-12:
        growth.peak_price = struct.peak_price
        growth.peak_ts = struct.peak_ts
        changed = True
    if struct.anchor_price > 0 and (
        struct.anchor_ts > growth.anchor_ts or struct.anchor_price != growth.anchor_price
    ):
        growth.anchor_price = struct.anchor_price
        growth.anchor_ts = struct.anchor_ts
        changed = True
    if growth.anchor_price > 0:
        growth.rally_pct = (last / growth.anchor_price - 1.0) * 100.0
    return changed


def evaluate_growth(
    state: SymbolState,
    tape: SymbolTape,
    growth: GrowthInfo,
    klines: dict[str, list[Bar]],
    now_ms: int,
) -> GrowthEvaluation:
    checks: dict[str, dict] = {}
    metrics: dict = {"growth": growth.to_data()}
    last = float(state.last_price or growth.peak_price)
    metrics["last_price"] = last

    struct = analyze_growth_swing_1h(klines.get("60") or [], now_ms, last)
    pullback_pct = pullback_pct_from_peak(growth.peak_price, last)
    metrics["pullback_from_peak_pct"] = _r(pullback_pct, 2)
    metrics["pullback_ok"] = pullback_entry_ok(pullback_pct)
    metrics["swing_1h"] = struct.to_metrics() if struct.hh_chain else {}

    checks["hh_structure_12h"] = _check(
        struct.valid and struct.higher_lows_ok,
        {
            "hh_count": len(struct.hh_chain),
            "higher_lows_ok": struct.higher_lows_ok,
            "hh_hours_between": struct.hh_hours_between,
        },
        f"≥ {config.PAPER_GROWTH_MIN_HH_COUNT:g} HH за {config.PAPER_GROWTH_STRUCTURE_HOURS:g} ч",
    )
    checks["pullback_entry"] = _check(
        pullback_entry_ok(pullback_pct),
        _r(pullback_pct, 2),
        f"{config.PAPER_GROWTH_PULLBACK_MIN_PCT:g}–{config.PAPER_GROWTH_PULLBACK_MAX_PCT:g}% от пика",
    )

    points = state.oi_points()
    oi_1h = oi_change_pct(points, lookback_min=60) if len(points) >= 2 else None
    oi_4h = oi_change_pct(points, lookback_min=240) if len(points) >= 2 else None
    checks["oi_1h_up"] = _check(oi_1h is not None and oi_1h > 0, _r(oi_1h, 2), "> 0%")
    checks["oi_4h_up"] = _check(oi_4h is not None and oi_4h > 0, _r(oi_4h, 2), "> 0%")

    buy_1h, sell_1h = tape.minute_window(now_ms, 60)
    buy_prev, sell_prev = tape.minute_window(now_ms - HOUR_MS, 60)
    buy_tot = buy_1h + sell_1h
    buy_share = buy_1h / buy_tot * 100.0 if buy_tot > 0 else None
    buys_rising = buy_1h > buy_prev and buy_prev > 0
    checks["buys_rising_1h"] = _check(
        buys_rising,
        {"last_h_usd": round(buy_1h), "prev_h_usd": round(buy_prev)},
        "больше прошлого часа",
    )
    checks["buy_share_60"] = _check(
        buy_share is not None and buy_share > config.PAPER_GROWTH_BUY_SHARE_MIN,
        _r(buy_share, 1),
        f"> {config.PAPER_GROWTH_BUY_SHARE_MIN:g}%",
    )

    vol_1h = sum(b.volume for b in state.bars_1m if b.timestamp >= now_ms - HOUR_MS)
    vol_1h_prev = sum(
        b.volume for b in state.bars_1m if now_ms - 2 * HOUR_MS <= b.timestamp < now_ms - HOUR_MS
    )
    vol_4h = sum(b.volume for b in state.bars_1m if b.timestamp >= now_ms - 4 * HOUR_MS)
    vol_4h_prev = sum(
        b.volume for b in state.bars_1m if now_ms - 8 * HOUR_MS <= b.timestamp < now_ms - 4 * HOUR_MS
    )
    g1 = _volume_growth_pct(vol_1h, vol_1h_prev)
    g4 = _volume_growth_pct(vol_4h, vol_4h_prev)
    min_pct = config.PAPER_GROWTH_VOL_GROWTH_MIN_PCT
    checks["volume_up_1h"] = _check(g1 is not None and g1 >= min_pct, _r(g1, 1), f"≥ {min_pct:g}%")
    checks["volume_up_4h"] = _check(g4 is not None and g4 >= min_pct, _r(g4, 1), f"≥ {min_pct:g}%")

    hourly = _hourly_volumes(state.bars_1m, now_ms, 4)
    avg_h = _avg_hourly_growth_pct(hourly)
    checks["volume_avg_4h"] = _check(
        avg_h is not None and avg_h >= min_pct,
        _r(avg_h, 1),
        f"≥ {min_pct:g}% в среднем за 4 ч",
    )

    emas = ema_table(klines, now_ms)
    ema_keys = config.PAPER_GROWTH_EMA_KEYS
    above = all(
        emas.get(k, {}).get("close") is not None
        and emas.get(k, {}).get("ema") is not None
        and emas[k]["close"] > emas[k]["ema"]
        for k in ema_keys
    )
    failed_emas = [
        k
        for k in ema_keys
        if not (
            emas.get(k, {}).get("close")
            and emas.get(k, {}).get("ema")
            and emas[k]["close"] > emas[k]["ema"]
        )
    ]
    checks["ema_above"] = _check(
        above,
        {"ok_count": len(ema_keys) - len(failed_emas), "total": len(ema_keys), "missing": failed_emas},
        "15m и 1H выше EMA50",
    )

    bars_1h = closed_bars(klines.get("60") or [], "60", now_ms)
    hh_hl = False
    if len(bars_1h) >= 2:
        a, b = bars_1h[-2], bars_1h[-1]
        hh_hl = b.high > a.high and b.low > a.low
    if struct.valid and len(struct.inter_lows) >= 1 and len(bars_1h) >= 1:
        hh_hl = hh_hl or (bars_1h[-1].low > struct.inter_lows[-1])
    checks["hh_hl_1h"] = _check(
        hh_hl,
        {"prev_h": _r(bars_1h[-2].high if len(bars_1h) >= 2 else None, 6), "last_h": _r(bars_1h[-1].high if bars_1h else None, 6)},
        "high/low последней 1H выше предыдущей",
    )

    vol_ratio = growth.volume_ratio_4h
    if vol_ratio is None and vol_4h_prev > 0:
        vol_ratio = vol_4h / vol_4h_prev
    turbo_vol = vol_ratio is not None and vol_ratio >= config.PAPER_GROWTH_TURBO_VOL_RATIO
    turbo_buys = buy_share is not None and buy_share >= config.PAPER_GROWTH_BUY_SHARE_TURBO
    turbo_oi = (oi_1h is not None and oi_1h > 0) or (oi_4h is not None and oi_4h > 0)
    turbo = turbo_vol and turbo_buys and turbo_oi and above

    checks["turbo_vol_x3"] = _check(
        turbo_vol,
        _r(vol_ratio, 2),
        f"≥ ×{config.PAPER_GROWTH_TURBO_VOL_RATIO:g} за 4 ч",
    )
    checks["turbo_buys_75"] = _check(
        turbo_buys,
        _r(buy_share, 1),
        f"≥ {config.PAPER_GROWTH_BUY_SHARE_TURBO:g}%",
    )

    score = 10.0 * sum(1 for k in GROWTH_MANDATORY if checks[k]["ok"]) + (15.0 if turbo else 0.0)
    metrics.update(
        {
            "oi_1h_pct": _r(oi_1h, 2),
            "oi_4h_pct": _r(oi_4h, 2),
            "buy_share_1h_pct": _r(buy_share, 1),
            "vol_growth_1h_pct": _r(g1, 1),
            "vol_growth_4h_pct": _r(g4, 1),
            "vol_avg_hourly_pct": _r(avg_h, 1),
            "volume_ratio_4h": _r(vol_ratio, 2),
            "ema": {k: v for k, v in emas.items()},
        }
    )
    return GrowthEvaluation(checks=checks, metrics=metrics, score=score, turbo=turbo)
