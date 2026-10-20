"""Виртуальный выход 333: −10% ROE → при +2.4% ROE лок +0.01% net → трейл 20% ROE от цены (best).

Прогон всех закрытых 333 по 1m свечам Bybit. Запуск на VPS:
  /opt/signals/.venv/bin/python scripts/simulate_333_exit_proposal.py
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from signal_engine.paper.position import (
    liquidation_price,
    long_liquidation_price,
    long_roe_pct,
    roe_pct,
    trail333_initial_stop,
    trail333_stop_long,
    trail333_stop_short,
)
from signal_engine.paper.trade_side import entry_from_raw, resolve_trade_side

FEE = config.PAPER_FEE_RATE_TAKER
CACHE_DIR = ROOT / "data" / "_kline_cache"


def db_path() -> Path:
    for p in (Path("/opt/signals/data/paper_strategy.db"), ROOT / "data" / "paper_strategy.db"):
        if p.is_file():
            return p
    raise FileNotFoundError("paper_strategy.db not found")


def net_pnl(
    side: str,
    entry: float,
    margin: float,
    leverage: int,
    exit_price: float,
    entry_fee: float,
    funding: float,
) -> float:
    qty = margin * leverage / entry
    if side == "long":
        gross = (exit_price - entry) * qty
    else:
        gross = (entry - exit_price) * qty
    exit_fee = qty * exit_price * FEE
    return gross - entry_fee - exit_fee + funding


def peak_roe(side: str, entry: float, best: float, lev: int) -> float:
    return long_roe_pct(entry, best, lev) if side == "long" else roe_pct(entry, best, lev)


def sync_stop(
    side: str,
    entry: float,
    best: float,
    margin: float,
    lev: int,
    entry_fee: float,
    funding: float,
    liq: float,
) -> float:
    if side == "long":
        s = trail333_stop_long(
            entry, best, 0.0, lev, margin=margin, entry_fee=entry_fee, funding_paid=funding
        )
        return max(liq, s)
    s = trail333_stop_short(
        entry, best, 0.0, lev, margin=margin, entry_fee=entry_fee, funding_paid=funding
    )
    return min(liq, s)


def fetch_klines_1m(symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float, float, float, float]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"333sim_{symbol}_{start_ms}_{end_ms}.json"
    if path.is_file():
        return [tuple(x) for x in json.loads(path.read_text(encoding="utf-8"))]

    out: list[tuple[int, float, float, float, float]] = []
    cursor = start_ms
    while cursor < end_ms:
        qs = urllib.parse.urlencode(
            {"category": "linear", "symbol": symbol, "interval": "1", "start": cursor, "limit": 1000}
        )
        url = f"https://api.bybit.com/v5/market/kline?{qs}"
        with urllib.request.urlopen(url, timeout=45) as resp:
            data = json.loads(resp.read().decode())
        rows = data.get("result", {}).get("list") or []
        if not rows:
            break
        batch = []
        for row in rows:
            ts = int(row[0])
            if start_ms <= ts <= end_ms:
                batch.append((ts, float(row[1]), float(row[2]), float(row[3]), float(row[4])))
        if not batch:
            break
        batch.sort(key=lambda x: x[0])
        out.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= cursor:
            break
        cursor = last_ts + 60_000
        time.sleep(0.04)
        if len(rows) < 1000:
            break
    by_ts = {t[0]: t for t in out}
    result = sorted(by_ts.values(), key=lambda x: x[0])
    path.write_text(json.dumps(result), encoding="utf-8")
    return result


@dataclass
class SimResult:
    pnl: float
    reason: str
    peak: float


def simulate_trade(trade: dict, bars: list) -> SimResult | None:
    entry = float(trade["entry_price"])
    margin = float(trade["margin"])
    lev = int(trade["leverage"])
    entry_fee = float(trade.get("entry_fee") or 0)
    funding = float(trade.get("funding_paid") or 0)
    side = resolve_trade_side(
        side=trade.get("side"),
        kind=trade.get("kind") or "",
        variant=trade.get("variant") or "333",
        entry=entry_from_raw(trade.get("entry_json")),
    )
    liq = float(trade.get("liq_price") or 0)
    if liq <= 0:
        liq = long_liquidation_price(entry, lev) if side == "long" else liquidation_price(entry, lev)

    opened = int(trade["opened_at"])
    closed = int(trade["closed_at"])
    best = entry
    max_peak = 0.0
    stop = sync_stop(side, entry, best, margin, lev, entry_fee, funding, liq, entry)

    def finish(px: float, reason: str) -> SimResult:
        return SimResult(
            net_pnl(side, entry, margin, lev, px, entry_fee, funding if reason == "eod" else 0.0),
            reason,
            max_peak,
        )

    for ts, _o, high, low, _c in bars:
        if ts < opened or ts > closed:
            continue
        if side == "long":
            if low <= liq:
                return finish(liq, "liquidation")
            if low <= stop:
                return finish(stop, "stop")
            if high > best:
                best = high
                max_peak = max(max_peak, peak_roe(side, entry, best, lev))
                stop = sync_stop(side, entry, best, margin, lev, entry_fee, funding, liq)
                if low <= stop:
                    return finish(stop, "stop")
        else:
            if high >= liq:
                return finish(liq, "liquidation")
            if high >= stop:
                return finish(stop, "stop")
            if low < best:
                best = low
                max_peak = max(max_peak, peak_roe(side, entry, best, lev))
                stop = sync_stop(side, entry, best, margin, lev, entry_fee, funding, liq)
                if high >= stop:
                    return finish(stop, "stop")

    last = [b for b in bars if opened <= b[0] <= closed]
    if not last:
        return None
    px = last[-1][4]
    return finish(px, "eod")


def summarize(pnls: list[float]) -> dict:
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    return {
        "n": n,
        "wins": wins,
        "wr": wins / n * 100 if n else 0.0,
        "total": sum(pnls),
        "avg": sum(pnls) / n if n else 0.0,
        "med": statistics.median(pnls) if pnls else 0.0,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM paper_trades WHERE variant = '333' AND status = 'closed' ORDER BY closed_at ASC"
    ).fetchall()
    trades = [dict(r) for r in rows]
    print(f"Закрытых 333: {len(trades)}")
    if not trades:
        return

    fact_pnls: list[float] = []
    sim_pnls: list[float] = []
    skipped = 0
    deltas: list[tuple[str, float, float, float]] = []

    for i, t in enumerate(trades, 1):
        fact = float(t.get("pnl_usd") or 0)
        fact_pnls.append(fact)
        start = int(t["opened_at"]) - 120_000
        end = int(t["closed_at"]) + 120_000
        sym = t["symbol"]
        try:
            bars = fetch_klines_1m(sym, start, end)
        except Exception as e:
            print(f"  skip {sym}: {e}")
            skipped += 1
            continue
        sim = simulate_trade(t, bars)
        if sim is None:
            skipped += 1
            continue
        sim_pnls.append(sim.pnl)
        deltas.append((sym, fact, sim.pnl, sim.pnl - fact))
        if i % 5 == 0:
            print(f"  ... {i}/{len(trades)}")

    fs = summarize(fact_pnls)
    ss = summarize(sim_pnls)
    print("\n--- Факт (как закрыто) ---")
    print(f"  n={fs['n']}  WR={fs['wr']:.1f}%  sum=${fs['total']:.2f}  avg=${fs['avg']:.2f}")
    print("\n--- Новый выход (симуляция) ---")
    print(f"  n={ss['n']}  WR={ss['wr']:.1f}%  sum=${ss['total']:.2f}  avg=${ss['avg']:.2f}")
    print(f"\n  Δ PnL (новый − факт): ${ss['total'] - fs['total']:+.2f}  (пропусков: {skipped})")

    deltas.sort(key=lambda x: x[3])
    print("\nХуже всего vs факт (новый − факт):")
    for sym, f, s, d in deltas[:5]:
        print(f"  {sym}: fact ${f:+.2f} → sim ${s:+.2f}  Δ ${d:+.2f}")
    print("\nЛучше всего vs факт:")
    for sym, f, s, d in deltas[-5:][::-1]:
        print(f"  {sym}: fact ${f:+.2f} → sim ${s:+.2f}  Δ ${d:+.2f}")


if __name__ == "__main__":
    main()
