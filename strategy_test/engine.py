"""MTF + перпы: intraday и scalp на BTC."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import config
from strategy_test import indicators as ind


@dataclass
class LivePerp:
    funding: float | None = None
    oi_last: float | None = None
    oi_ref: float | None = None
    oi_ref_ts: float = 0.0
    liq_short: float = 0.0
    liq_long: float = 0.0
    liq_window: list[tuple[float, float, float]] = field(default_factory=list)


@dataclass
class OpenTrade:
    id: int
    mode: str
    side: str
    entry_price: float
    entry_ts: int
    stop: float
    tp: float
    risk: float
    max_hold_sec: int


class BtcStrategyEngine:
    SYMBOL = config.BTC_TEST_SYMBOL

    def __init__(self) -> None:
        self.bars: dict[str, list[dict[str, float]]] = {}
        self.last_price: float | None = None
        self.perp = LivePerp()
        self.open: dict[str, OpenTrade | None] = {"intraday": None, "scalp": None}
        self._cooldown: dict[str, int] = {}
        self.bias: str = "FLAT"
        self.markers: list[dict[str, Any]] = []

    def set_bars(self, interval: str, rows: list[dict[str, float]]) -> None:
        self.bars[interval] = rows

    def on_trade(self, price: float, ts_ms: int) -> None:
        self.last_price = price

    def on_ticker(self, funding: float | None) -> None:
        if funding is not None:
            self.perp.funding = funding

    def on_oi(self, value: float, ts_ms: int) -> None:
        now = ts_ms / 1000
        if self.perp.oi_ref is None or now - self.perp.oi_ref_ts > 900:
            self.perp.oi_ref = value
            self.perp.oi_ref_ts = now
        self.perp.oi_last = value

    def on_liquidation(self, side: str, usd: float, ts_ms: int) -> None:
        t = ts_ms / 1000
        self.perp.liq_window.append((t, side, usd))
        cutoff = t - 900
        self.perp.liq_window = [x for x in self.perp.liq_window if x[0] >= cutoff]
        self.perp.liq_short = sum(u for tt, s, u in self.perp.liq_window if s == "Sell")
        self.perp.liq_long = sum(u for tt, s, u in self.perp.liq_window if s == "Buy")

    def _closes(self, interval: str) -> list[float]:
        b = self.bars.get(interval) or []
        return [float(x["c"]) for x in b]

    def _volumes(self, interval: str) -> list[float]:
        b = self.bars.get(interval) or []
        return [float(x.get("v") or 0) for x in b]

    def _last(self, interval: str) -> dict[str, float] | None:
        b = self.bars.get(interval) or []
        return b[-1] if b else None

    def _update_bias(self) -> None:
        c4 = self._closes("240")
        c1 = self._closes("60")
        cd = self._closes("D")
        if len(c4) < 55 or len(c1) < 55:
            self.bias = "FLAT"
            return
        e20_4 = ind.ema(c4, 20)[-1]
        e50_4 = ind.ema(c4, 50)[-1]
        e20_1 = ind.ema(c1, 20)[-1]
        if e20_4 is None or e50_4 is None or e20_1 is None:
            self.bias = "FLAT"
            return
        up = c4[-1] > e50_4 and e20_4 > e50_4 and c1[-1] > e20_1
        down = c4[-1] < e50_4 and e20_4 < e50_4 and c1[-1] < e20_1
        if up:
            self.bias = "LONG"
        elif down:
            self.bias = "SHORT"
        else:
            self.bias = "BOTH"

    def _day_veto(self, side: str) -> bool:
        cd = self._closes("D")
        if len(cd) < 55:
            return True
        e50 = ind.ema(cd, 50)[-1]
        e20 = ind.ema(cd, 20)[-1]
        if e50 is None or e20 is None:
            return True
        if side == "long" and cd[-1] < e50 and e20 < e50:
            return False
        if side == "short" and cd[-1] > e50 and e20 > e50:
            return False
        return True

    def _perp_checks(self, side: str) -> tuple[dict[str, bool], int]:
        checks = {
            "vol_perp": False,
            "funding_perp": False,
            "oi_perp": False,
            "liq_perp": False,
        }
        vols = self._volumes("5")
        if len(vols) >= 21:
            sma = ind.sma(vols, 20)[-1]
            if sma and vols[-1] >= 1.2 * sma:
                checks["vol_perp"] = True
        fr = self.perp.funding
        if fr is not None:
            if side == "long" and fr <= 0.0003:
                checks["funding_perp"] = True
            if side == "short" and fr >= 0.0005:
                checks["funding_perp"] = True
        if self.perp.oi_last and self.perp.oi_ref and self.perp.oi_ref > 0:
            chg = (self.perp.oi_last - self.perp.oi_ref) / self.perp.oi_ref * 100
            if side == "long" and chg >= -0.2:
                checks["oi_perp"] = True
            if side == "short" and chg <= 0.2:
                checks["oi_perp"] = True
        if side == "long" and self.perp.liq_short > self.perp.liq_long * 1.5:
            checks["liq_perp"] = True
        if side == "short" and self.perp.liq_long > self.perp.liq_short * 1.5:
            checks["liq_perp"] = True
        return checks, sum(1 for v in checks.values() if v)

    def _mtf_checks(self, side: str, mode: str) -> tuple[dict[str, bool], int]:
        checks: dict[str, bool] = {
            "d_veto_ok": self._day_veto(side),
            "bias_4h": False,
            "bias_1h": False,
            "m30_structure": False,
            "m15_vol": False,
            "m5_trigger": False,
            "m1_trigger": False,
        }
        if self.bias == "LONG" and side == "long":
            checks["bias_4h"] = checks["bias_1h"] = True
        elif self.bias == "SHORT" and side == "short":
            checks["bias_4h"] = checks["bias_1h"] = True
        elif self.bias == "BOTH":
            checks["bias_4h"] = checks["bias_1h"] = True

        c30 = self._closes("30")
        if len(c30) >= 25:
            e20 = ind.ema(c30, 20)[-1]
            if e20:
                if side == "long" and c30[-1] >= e20 * 0.999:
                    checks["m30_structure"] = True
                if side == "short" and c30[-1] <= e20 * 1.001:
                    checks["m30_structure"] = True

        c15 = self._closes("15")
        vol15 = self._volumes("15")
        if len(c15) >= 25 and len(vol15) >= 21:
            e20 = ind.ema(c15, 20)[-1]
            sma = ind.sma(vol15, 20)[-1]
            if e20 and sma and vol15[-1] >= 1.1 * sma:
                if side == "long" and c15[-1] > e20:
                    checks["m15_vol"] = True
                if side == "short" and c15[-1] < e20:
                    checks["m15_vol"] = True

        c5 = self._closes("5")
        if len(c5) >= 25:
            e9 = ind.ema(c5, 9)[-1]
            rs = ind.rsi(c5, 14)
            if e9 and rs[-1] is not None and rs[-2] is not None:
                cross_up = rs[-2] < 50 <= rs[-1]
                cross_dn = rs[-2] > 50 >= rs[-1]
                if side == "long" and c5[-1] > e9 and cross_up:
                    checks["m5_trigger"] = True
                if side == "short" and c5[-1] < e9 and cross_dn:
                    checks["m5_trigger"] = True

        if mode == "scalp":
            c1 = self._closes("1")
            if len(c1) >= 20:
                e9 = ind.ema(c1, 9)[-1]
                rs = ind.rsi(c1, 14)
                if e9 and rs[-1] is not None:
                    if side == "long" and c1[-1] > e9 and rs[-1] > 48:
                        checks["m1_trigger"] = True
                    if side == "short" and c1[-1] < e9 and rs[-1] < 52:
                        checks["m1_trigger"] = True
        else:
            checks["m1_trigger"] = True

        return checks, sum(1 for v in checks.values() if v)

    def _grade(self, score: int) -> str:
        if score >= 9:
            return "A"
        if score >= 7:
            return "B"
        return "C"

    def _try_entry(self, mode: str, side: str, now_ms: int) -> dict[str, Any] | None:
        if self.open.get(mode):
            return None
        key = f"{mode}:{side}"
        if now_ms - self._cooldown.get(key, 0) < 180_000:
            return None
        if self.bias == "LONG" and side == "short":
            return None
        if self.bias == "SHORT" and side == "long":
            return None
        mtf, mtf_score = self._mtf_checks(side, mode)
        if not mtf.get("d_veto_ok"):
            return None
        need_mtf = 5 if mode == "intraday" else 4
        if mtf_score < need_mtf:
            return None
        perp, perp_score = self._perp_checks(side)
        if perp_score < 1:
            return None
        checks = {**mtf, **perp}
        score = mtf_score + perp_score
        grade = self._grade(score)
        price = self.last_price or (self._last("5") or {}).get("c")
        if not price:
            return None
        atr_iv = "15" if mode == "intraday" else "5"
        highs = [float(x["h"]) for x in self.bars.get(atr_iv) or []]
        lows = [float(x["l"]) for x in self.bars.get(atr_iv) or []]
        closes = self._closes(atr_iv)
        atr_v = ind.atr(highs, lows, closes, 14)[-1] if len(closes) > 15 else None
        if not atr_v:
            return None
        mult = 1.2 if mode == "intraday" else 0.9
        tp_mult = 1.0 if mode == "intraday" else 0.6
        if side == "long":
            stop = price - mult * atr_v
            risk = price - stop
            tp = price + tp_mult * risk
        else:
            stop = price + mult * atr_v
            risk = stop - price
            tp = price - tp_mult * risk
        hold = 8 * 3600 if mode == "intraday" else 4 * 3600
        self._cooldown[key] = now_ms
        return {
            "mode": mode,
            "side": side,
            "grade": grade,
            "score": score,
            "entry_ts": now_ms,
            "entry_price": float(price),
            "stop": stop,
            "tp": tp,
            "risk": risk,
            "max_hold_sec": hold,
            "checks": checks,
        }

    def scan_entries(self, now_ms: int | None = None) -> list[dict[str, Any]]:
        now_ms = now_ms or int(time.time() * 1000)
        self._update_bias()
        out: list[dict[str, Any]] = []
        for mode in ("intraday", "scalp"):
            for side in ("long", "short"):
                sig = self._try_entry(mode, side, now_ms)
                if sig:
                    out.append(sig)
        return out

    def update_exits(self, now_ms: int | None = None) -> list[dict[str, Any]]:
        now_ms = now_ms or int(time.time() * 1000)
        price = self.last_price
        if price is None:
            return []
        closed: list[dict[str, Any]] = []
        for mode, trade in list(self.open.items()):
            if trade is None:
                continue
            reason = None
            if trade.side == "long":
                if price <= trade.stop:
                    reason = "SL"
                elif price >= trade.tp:
                    reason = "TP"
            else:
                if price >= trade.stop:
                    reason = "SL"
                elif price <= trade.tp:
                    reason = "TP"
            if (now_ms - trade.entry_ts) / 1000 >= trade.max_hold_sec:
                reason = reason or "TIME"
            if reason:
                closed.append(self._close_trade(mode, trade, now_ms, price, reason))
        return closed

    def _close_trade(
        self, mode: str, trade: OpenTrade, exit_ts: int, exit_price: float, reason: str
    ) -> dict[str, Any]:
        self.open[mode] = None
        if trade.side == "long":
            pnl = (exit_price - trade.entry_price) / trade.entry_price * 100 * config.PNL_LEVERAGE
            r_mult = (exit_price - trade.entry_price) / trade.risk if trade.risk else 0
        else:
            pnl = (trade.entry_price - exit_price) / trade.entry_price * 100 * config.PNL_LEVERAGE
            r_mult = (trade.entry_price - exit_price) / trade.risk if trade.risk else 0
        outcome = "WIN" if pnl > 0 else "LOSS"
        return {
            "id": trade.id,
            "mode": mode,
            "side": trade.side,
            "exit_ts": exit_ts,
            "exit_price": exit_price,
            "outcome": outcome,
            "pnl_pct": pnl,
            "r_multiple": r_mult,
            "exit_reason": reason,
        }

    def register_open(self, trade: OpenTrade) -> None:
        self.open[trade.mode] = trade

    def chart_candles(self, interval: str = "5", limit: int = 200) -> list[dict[str, Any]]:
        rows = (self.bars.get(interval) or [])[-limit:]
        out = []
        for r in rows:
            out.append(
                {
                    "time": int(r["t"] // 1000),
                    "open": r["o"],
                    "high": r["h"],
                    "low": r["l"],
                    "close": r["c"],
                }
            )
        return out

    def public_state(self, signals: list[dict[str, Any]], analytics: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": self.SYMBOL,
            "bias": self.bias,
            "last_price": self.last_price,
            "funding": self.perp.funding,
            "candles": self.chart_candles("5"),
            "markers": self.markers[-80:],
            "signals": signals,
            "analytics": analytics,
            "open": {
                k: {
                    "side": v.side,
                    "entry_price": v.entry_price,
                    "entry_ts": v.entry_ts,
                    "mode": v.mode,
                }
                if v
                else None
                for k, v in self.open.items()
            },
        }
