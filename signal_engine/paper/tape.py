"""Лента для теста стратегии: агрессивные покупки/продажи и ликвидации в USDT.

Сделки копятся в 5-минутные корзины на сутки с запасом — по ним считается
доля покупок на всей ноге роста. Ликвидации — поминутно, лонги и шорты отдельно.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config

BUCKET_MS = 5 * 60_000
MINUTE_MS = 60_000
_LIQ_KEEP_MS = 180 * MINUTE_MS


def bucket_start(ts: int) -> int:
    return (ts // BUCKET_MS) * BUCKET_MS


def minute_start(ts: int) -> int:
    return (ts // MINUTE_MS) * MINUTE_MS


@dataclass
class SymbolTape:
    buckets: dict[int, list[float]] = field(default_factory=dict)
    minutes: dict[int, list[float]] = field(default_factory=dict)
    liq_long: dict[int, float] = field(default_factory=dict)
    liq_short: dict[int, float] = field(default_factory=dict)
    first_ts: int | None = None
    next_funding_ts: int | None = None

    def add_trade(self, ts: int, side: str | None, notional: float) -> None:
        if notional <= 0 or side not in ("Buy", "Sell"):
            return
        idx = 0 if side == "Buy" else 1
        key = bucket_start(ts)
        row = self.buckets.get(key)
        if row is None:
            row = [0.0, 0.0]
            self.buckets[key] = row
            self._trim_buckets(key)
        row[idx] += notional
        minute = minute_start(ts)
        mrow = self.minutes.get(minute)
        if mrow is None:
            mrow = [0.0, 0.0]
            self.minutes[minute] = mrow
            self._trim_minutes(minute)
        mrow[idx] += notional
        if self.first_ts is None or ts < self.first_ts:
            self.first_ts = ts

    def add_liquidation(self, ts: int, side: str | None, notional: float) -> None:
        # Bybit allLiquidation: Buy — ликвидирован лонг, Sell — ликвидирован шорт.
        if notional <= 0:
            return
        minute = minute_start(ts)
        target = self.liq_long if side == "Buy" else self.liq_short if side == "Sell" else None
        if target is None:
            return
        if minute not in target:
            for key in [k for k in target if k < minute - _LIQ_KEEP_MS]:
                del target[key]
        target[minute] = target.get(minute, 0.0) + notional

    def _trim_buckets(self, newest: int) -> None:
        cutoff = newest - config.PAPER_TAPE_RETENTION_HOURS * 3_600_000
        for key in [k for k in self.buckets if k < cutoff]:
            del self.buckets[key]

    def _trim_minutes(self, newest: int) -> None:
        cutoff = newest - 180 * MINUTE_MS
        for key in [k for k in self.minutes if k < cutoff]:
            del self.minutes[key]

    def buy_sell_between(self, start_ms: int, end_ms: int) -> tuple[float, float, int]:
        """Покупки, продажи и сколько минут ленты реально есть в окне [start, end]."""
        buy = sell = 0.0
        covered = 0
        for key, (b, s) in self.buckets.items():
            if key + BUCKET_MS <= start_ms or key > end_ms:
                continue
            buy += b
            sell += s
            covered += 5
        return buy, sell, covered

    def minute_window(self, now_ms: int, minutes: int) -> tuple[float, float]:
        """Покупки и продажи за последние N минут, включая текущую."""
        current = minute_start(now_ms)
        start = current - (minutes - 1) * MINUTE_MS
        buy = sell = 0.0
        for key, (b, s) in self.minutes.items():
            if start <= key <= current:
                buy += b
                sell += s
        return buy, sell

    def peak_buy_window(self, now_ms: int, minutes: int, lookback_min: int = 180) -> float:
        """Максимум суммы покупок в скользящем окне N минут за lookback."""
        current = minute_start(now_ms)
        start = current - (lookback_min - 1) * MINUTE_MS
        series = [
            (self.minutes.get(start + i * MINUTE_MS) or (0.0, 0.0))[0]
            for i in range(lookback_min)
        ]
        best = running = 0.0
        for i, value in enumerate(series):
            running += value
            if i >= minutes:
                running -= series[i - minutes]
            best = max(best, running)
        return best

    def liq_series(self, now_ms: int, minutes: int, side: str) -> list[float]:
        source = self.liq_long if side == "long" else self.liq_short
        current = minute_start(now_ms)
        start = current - (minutes - 1) * MINUTE_MS
        return [float(source.get(start + i * MINUTE_MS, 0.0)) for i in range(minutes)]


class TapeBook:
    def __init__(self) -> None:
        self.symbols: dict[str, SymbolTape] = {}

    def get(self, symbol: str) -> SymbolTape:
        tape = self.symbols.get(symbol)
        if tape is None:
            tape = SymbolTape()
            self.symbols[symbol] = tape
        return tape

    def ingest(self, message: dict) -> None:
        kind = message.get("type")
        if kind not in ("trade", "liquidation", "ticker"):
            return
        symbol = message.get("symbol")
        if not symbol:
            return
        data = message.get("data") or {}
        ts = int(message.get("timestamp") or 0)
        if kind == "ticker":
            nft = data.get("next_funding_time")
            if nft:
                try:
                    self.get(symbol).next_funding_ts = int(nft)
                except (TypeError, ValueError):
                    pass
            return
        try:
            price = float(data.get("price") or 0)
            size = float(data.get("size") or 0)
        except (TypeError, ValueError):
            return
        if price <= 0 or size <= 0 or ts <= 0:
            return
        tape = self.get(symbol)
        if kind == "trade":
            tape.add_trade(ts, data.get("side"), price * size)
        else:
            tape.add_liquidation(ts, data.get("side"), price * size)
