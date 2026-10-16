# -*- coding: utf-8 -*-
"""Single $1000 mt2c account on cached 15m klines (chart entry, p10 exit)."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import config
from signal_engine.paper.position import Position

DIR = os.path.join(os.environ.get("TEMP", "/tmp"), "mt2_bt")
MIN = 60_000
TF15 = 15 * MIN
HOUR = 60 * MIN
DAY = 24 * HOUR
START = config.PAPER_START_BALANCE_USD
COOLDOWN = config.PAPER_REENTRY_COOLDOWN_SEC * 1000
FLOORS = {
    "4h": config.PAPER_SHORT_4H_MIN_PCT * config.PAPER_MINI_PUMP_SCALE,
    "24h": config.PAPER_SHORT_24H_MIN_PCT * config.PAPER_MINI_PUMP_SCALE,
}


@dataclass
class Signal:
    symbol: str
    entry_ts: int
    exit_ts: int
    entry_i: int
    exit_i: int
    reason: str


@dataclass
class Account:
    balance: float = START
    used: float = 0.0
    closed: list[dict] = field(default_factory=list)
    last_close: dict[str, int] = field(default_factory=dict)
    peak_open: int = 0

    def free(self) -> float:
        return self.balance - self.used

    def margin_size(self) -> float:
        return self.balance * config.PAPER_MARGIN_PCT / 100.0


def resample(bars, minutes):
    step = minutes * MIN
    groups = {}
    for b in bars:
        key = b["ts"] // step * step
        g = groups.get(key)
        if g is None:
            groups[key] = {"ts": key, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]}
        else:
            g["h"] = max(g["h"], b["h"])
            g["l"] = min(g["l"], b["l"])
            g["c"] = b["c"]
            g["v"] += b["v"]
    return [groups[k] for k in sorted(groups)]


def prep(bars):
    from signal_engine.indicators import ema

    b30 = resample(bars, 30)
    b60 = resample(bars, 60)
    return {
        "e15": {p: ema([b["c"] for b in bars], p) for p in (50, 100, 200)},
        "b30": b30,
        "b60": b60,
        "e30": {p: ema([b["c"] for b in b30], p) for p in (50, 100, 200)},
        "e60": {p: ema([b["c"] for b in b60], p) for p in (50, 100, 200)},
    }


def ema_broken(closes, emas, idx):
    close = closes[idx]
    for values in emas.values():
        v = values[idx] if idx < len(values) else None
        if v is not None and close < v:
            return True
    return False


def window_min(bars, peak_i, window_ms):
    peak_ts = bars[peak_i]["ts"]
    rows = [b for b in bars if peak_ts - window_ms <= b["ts"] <= peak_ts]
    return min(b["l"] for b in rows) if rows else None


def pump_trigger(bars, peak_i):
    peak = bars[peak_i]["h"]
    now = bars[peak_i]["ts"] + TF15
    peak_ts = bars[peak_i]["ts"] + TF15
    since = now - peak_ts
    v4 = window_min(bars, peak_i, 4 * HOUR)
    v24 = window_min(bars, peak_i, DAY)
    g4 = (peak / v4 - 1) * 100 if v4 else None
    g24 = (peak / v24 - 1) * 100 if v24 else None
    if since <= config.PAPER_SHORT_LIFETIME_HOURS * HOUR:
        if g4 is not None and g4 > FLOORS["4h"]:
            return True
        if g24 is not None and g24 >= FLOORS["24h"]:
            return True
    return False


def leg_vol(bars, peak_i):
    peak_ts = bars[peak_i]["ts"]
    start = peak_ts - 4 * HOUR
    leg = [b for b in bars[max(0, peak_i - 20): peak_i + 1] if b["ts"] >= start]
    base = [b for b in bars[max(0, peak_i - 40): peak_i] if leg and b["ts"] < leg[0]["ts"]][-20:]
    if len(leg) < 2 or len(base) < 5:
        return None
    mean = sum(b["v"] for b in base) / len(base)
    return max(b["v"] for b in leg) / mean if mean > 0 else None


def entry_ok(bars, i, peak_i, meta):
    bar = bars[i]
    now = bar["ts"] + TF15
    peak = bars[peak_i]["h"]
    dd = (1 - bar["c"] / peak) * 100
    since_min = (now - (bars[peak_i]["ts"] + TF15)) / MIN
    if not pump_trigger(bars, peak_i):
        return False
    i30 = (i + 1) // 2 - 1
    i60 = (i + 1) // 4 - 1
    broken = (
        ema_broken([b["c"] for b in bars], meta["e15"], i)
        or (i30 >= 0 and ema_broken([b["c"] for b in meta["b30"]], meta["e30"], i30))
        or (i60 >= 0 and ema_broken([b["c"] for b in meta["b60"]], meta["e60"], i60))
    )
    volx = leg_vol(bars, peak_i)
    if not (6 <= since_min <= 180 and dd <= config.PAPER_MINI_MAX_DRAWDOWN_PCT and not broken):
        return False
    if since_min > config.PAPER_ENTRY_LATE_MIN and volx is not None and volx >= config.PAPER_ENTRY_MEGAVOL_RATIO:
        return False
    return True


def collect_signals(bars, sym, meta, test_from):
    out = []
    i = 200
    while i < len(bars) - 1:
        ts = bars[i]["ts"] + TF15
        if ts < test_from:
            i += 1
            continue
        left = i
        while left > 0 and bars[left]["ts"] >= ts - config.PAPER_LONG_LIFETIME_HOURS * HOUR:
            left -= 1
        window = bars[left: i + 1]
        peak_i = left + max(range(len(window)), key=lambda k: window[k]["h"])
        if not entry_ok(bars, i, peak_i, meta):
            i += 1
            continue
        pos = Position(
            symbol=sym,
            opened_at=ts,
            entry_price=bars[i]["c"],
            margin=50.0,
            peak_gap_roe=config.paper_peak_gap_roe("mt2c"),
            last_price=bars[i]["c"],
        )
        reason = None
        exit_i = len(bars) - 1
        for j in range(i + 1, len(bars)):
            reason = pos.update(bars[j]["l"], bars[j]["h"], bars[j]["c"])
            if reason:
                exit_i = j
                break
        out.append(
            Signal(sym, ts, bars[exit_i]["ts"] + TF15, i, exit_i, reason or "eod")
        )
        i = exit_i + 1
    return out


@dataclass
class OpenLeg:
    sig: Signal
    margin: float


def _close_leg(acc: Account, leg: OpenLeg, books: dict[str, list]) -> None:
    sig = leg.sig
    bars = books[sig.symbol]
    pos = Position(
        symbol=sig.symbol,
        opened_at=sig.entry_ts,
        entry_price=bars[sig.entry_i]["c"],
        margin=leg.margin,
        peak_gap_roe=config.paper_peak_gap_roe("mt2c"),
        last_price=bars[sig.entry_i]["c"],
    )
    reason = None
    for j in range(sig.entry_i + 1, sig.exit_i + 1):
        reason = pos.update(bars[j]["l"], bars[j]["h"], bars[j]["c"])
        if reason:
            break
    result = pos.close_result(reason or sig.reason)
    acc.balance += result["pnl_usd"]
    acc.used -= leg.margin
    acc.last_close[sig.symbol] = sig.exit_ts
    acc.closed.append(
        {
            "symbol": sig.symbol,
            "pnl": round(result["pnl_usd"], 2),
            "roe": round(result["roe_pct"], 2),
            "margin": round(leg.margin, 2),
        }
    )


def run_account(signals: list[Signal], books: dict[str, list]):
    acc = Account()
    open_legs: list[OpenLeg] = []
    skipped = 0
    for sig in sorted(signals, key=lambda s: s.entry_ts):
        still: list[OpenLeg] = []
        for leg in open_legs:
            if leg.sig.exit_ts <= sig.entry_ts:
                _close_leg(acc, leg, books)
            else:
                still.append(leg)
        open_legs = still
        acc.peak_open = max(acc.peak_open, len(open_legs))

        if sig.entry_ts - acc.last_close.get(sig.symbol, 0) < COOLDOWN:
            skipped += 1
            continue
        if any(leg.sig.symbol == sig.symbol for leg in open_legs):
            skipped += 1
            continue
        margin = acc.margin_size()
        if margin <= 0 or acc.free() < margin:
            skipped += 1
            continue
        acc.used += margin
        open_legs.append(OpenLeg(sig, margin))

    for leg in open_legs:
        _close_leg(acc, leg, books)
    return acc, skipped


def main():
    trades_path = os.path.join(DIR, "trades.json")
    if os.path.isfile(trades_path):
        syms = sorted({t["symbol"] for t in json.load(open(trades_path, encoding="utf-8"))})
    else:
        syms = [n[:-len("_15.json")] for n in os.listdir(DIR) if n.endswith("_15.json")]
    books = {}
    signals = []
    for sym in syms:
        path = os.path.join(DIR, f"{sym}_15.json")
        if not os.path.isfile(path):
            continue
        bars = json.load(open(path, encoding="utf-8"))
        if len(bars) < 220:
            continue
        books[sym] = bars
        test_from = bars[-1]["ts"] - 7 * DAY
        signals.extend(collect_signals(bars, sym, prep(bars), test_from))

    acc, skipped = run_account(signals, books)
    wins = sum(1 for t in acc.closed if t["pnl"] > 0)
    print(f"symbols {len(books)} chart signals {len(signals)}")
    print(f"taken {len(acc.closed)} skipped {skipped} (cooldown or margin)")
    print(f"balance {acc.balance:.2f} pnl {acc.balance - START:+.2f} wr {100*wins/len(acc.closed) if acc.closed else 0:.1f}%")
    print(f"peak concurrent {acc.peak_open}  |  naive sum all signals $50: sum pnl not shown")
    print("compare: live mt2 ~125 trades +$57; chart sum 461 x $50 independent +$1694")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
