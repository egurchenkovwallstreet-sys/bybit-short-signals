"""Кэш рыночных данных для карточки. Браузер получает уже собранный снимок.

Стакан: снимок заменяет книгу, дельта с размером 0 снимает уровень.
Стены: крупный уровень, который держится — Holding, который вырос — Building,
который исчез сразу после появления — Spoof.
"""

from __future__ import annotations

import time
from typing import Any

import config
from signal_engine.outcomes import short_pnl_pct


def _ts_ms(raw: Any) -> int | None:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n if n > 1_000_000_000_000 else n * 1000


def _trim_time_window(rows: list[dict[str, Any]], time_key: str = "timestamp") -> list[dict[str, Any]]:
    if not rows:
        return []
    window_ms = config.DETAIL_CHART_WINDOW_HOURS * 3600 * 1000
    cutoff = int(time.time() * 1000) - window_ms
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = _ts_ms(row.get(time_key) if time_key in row else row.get("time"))
        if ts is not None and ts >= cutoff:
            out.append(row)
    if out:
        return out
    tail = rows[-min(len(rows), 120) :]
    return list(tail)


class MarketCache:
    def __init__(self) -> None:
        self.columns: list[dict[str, Any]] = []
        self.signals: dict[str, dict[str, Any]] = {}
        self.klines: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.books: dict[str, dict[str, Any]] = {}
        self._book_age: dict[str, dict[float, int]] = {}
        self.liquidations: dict[str, list[dict[str, Any]]] = {}
        self.cvd: dict[str, list[dict[str, float]]] = {}
        self._cvd_value: dict[str, float] = {}
        self.oi: dict[str, list[dict[str, Any]]] = {}
        self.funding: dict[str, float] = {}
        self.taker_buy: dict[str, float] = {}
        self.taker_sell: dict[str, float] = {}
        self.mini: dict[str, list[float]] = {}
        self.turnover_24h: dict[str, float] = {}

    def apply(self, message: dict[str, Any]) -> str | None:
        kind = message.get("type")
        if kind == "board":
            self.columns = list((message.get("data") or {}).get("columns") or [])
            self._reindex()
            return "board"
        if kind == "signal":
            self._upsert_signal(message.get("data") or {})
            return "board"
        if kind in {"trade", "kline", "orderbook", "liquidation", "ticker", "open_interest"}:
            self._market(message)
            return "market"
        return None

    def view_board(self) -> list[dict[str, Any]]:
        """Колонки для браузера: мини-график и живой P&L шорта."""
        view = []
        for column in self.columns:
            signals = []
            for signal in column.get("signals") or []:
                symbol = signal.get("symbol") or ""
                if not self._signal_turnover_ok(symbol):
                    continue
                item = dict(signal)
                item["mini"] = self.mini_closes(symbol)
                entry = item.get("entry_price")
                price = item.get("last_price")
                if item.get("strength") == 5 and entry and price:
                    item["pnl_pct"] = short_pnl_pct(float(entry), float(price))
                signals.append(item)
            view.append({**column, "signals": signals})
        return view

    def pnl_items(self) -> list[dict[str, Any]]:
        items = []
        for symbol, signal in self.signals.items():
            if signal.get("strength") != 5:
                continue
            entry = signal.get("entry_price")
            price = signal.get("last_price")
            if not entry or not price:
                continue
            items.append(
                {
                    "symbol": symbol,
                    "last_price": price,
                    "pnl_pct": short_pnl_pct(float(entry), float(price)),
                }
            )
        return items

    def detail(self, symbol: str, interval: str) -> dict[str, Any]:
        signal = self.signals.get(symbol)
        buy = self.taker_buy.get(symbol, 0.0)
        sell = self.taker_sell.get(symbol, 0.0)
        ratio = None
        if buy or sell:
            ratio = float("inf") if sell == 0 else buy / sell
            if ratio == float("inf"):
                ratio = None
        elif signal and signal.get("taker_ratio") is not None:
            ratio = signal.get("taker_ratio")
        return {
            "signal": signal,
            "interval": interval,
            "candles": self.klines.get((symbol, interval), []),
            "book": self.book_view(symbol),
            "liquidations": _trim_time_window(self.liquidations.get(symbol, [])[-400:], "time"),
            "oi": _trim_time_window(self.oi.get(symbol, []), "timestamp"),
            "cvd": _trim_time_window(self.cvd.get(symbol, []), "time"),
            "obv": _trim_time_window(self._obv(symbol), "time"),
            "funding_rate": self.funding.get(symbol),
            "taker_ratio": ratio,
            "mini": self.mini_closes(symbol),
        }

    def book_view(self, symbol: str) -> dict[str, Any]:
        book = self.books.get(symbol) or {"bids": [], "asks": [], "walls": []}
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        if isinstance(bids, dict):
            bids = sorted(bids.items(), reverse=True)
        if isinstance(asks, dict):
            asks = sorted(asks.items())
        return {"bids": bids, "asks": asks, "walls": book.get("walls") or []}

    def _signal_turnover_ok(self, symbol: str) -> bool:
        if not symbol:
            return False
        turnover = self.turnover_24h.get(symbol)
        if turnover is None:
            return False
        return turnover >= config.UNIVERSE_MIN_TURNOVER_24H_USDT

    def mini_closes(self, symbol: str) -> list[float]:
        if self.mini.get(symbol):
            return self.mini[symbol][-30:]
        candles = self.klines.get((symbol, "1"), [])
        return [float(item["close"]) for item in candles[-30:]]

    def _reindex(self) -> None:
        self.signals = {}
        for column in self.columns:
            for signal in column.get("signals") or []:
                symbol = signal.get("symbol")
                if symbol:
                    self.signals[symbol] = signal

    def _upsert_signal(self, data: dict[str, Any]) -> None:
        symbol = data.get("symbol")
        if not symbol or data.get("outcome"):
            if symbol:
                self.signals.pop(symbol, None)
                for column in self.columns:
                    column["signals"] = [
                        item for item in column.get("signals") or [] if item.get("symbol") != symbol
                    ]
            return
        current = self.signals.get(symbol)
        if current is not None:
            current.update(data)
            return
        self.signals[symbol] = data
        for column in self.columns:
            if column.get("strength") == data.get("strength"):
                column.setdefault("signals", []).append(data)
                return
        # Колонки ещё не приходили доской — карточка появится со следующим board.

    def _market(self, message: dict[str, Any]) -> None:
        symbol = str(message.get("symbol") or "")
        if not symbol:
            return
        kind = message.get("type")
        data = message.get("data") or {}
        timestamp = int(message.get("timestamp") or 0)
        if kind == "trade":
            self._trade(symbol, timestamp, data)
        elif kind == "kline":
            interval = str(data.get("interval") or "")
            candles = data.get("candles") or []
            if interval and candles:
                key = (symbol, interval)
                prev = self.klines.get(key) or []
                if len(candles) >= len(prev):
                    self.klines[key] = list(candles)
                elif len(prev) >= 100 and len(candles) <= 3:
                    merged = {int(c["timestamp"]): c for c in prev if c.get("timestamp")}
                    for c in candles:
                        ts = c.get("timestamp")
                        if ts is not None:
                            merged[int(ts)] = c
                    self.klines[key] = sorted(merged.values(), key=lambda item: item["timestamp"])
        elif kind == "orderbook":
            self._book(symbol, data)
        elif kind == "liquidation" and data.get("side") == "Sell":
            price = _num(data.get("price"))
            size = _num(data.get("size"))
            if price and size:
                bucket = self.liquidations.setdefault(symbol, [])
                bucket.append({"time": timestamp, "price": price, "size": size})
                del bucket[:-400]
        elif kind == "ticker":
            rate = _num(data.get("funding_rate"))
            if rate is not None:
                self.funding[symbol] = rate
            turnover = _num(data.get("turnover_24h"))
            if turnover is not None:
                self.turnover_24h[symbol] = turnover
            price = _num(data.get("last_price"))
            if price:
                self._touch_price(symbol, price)
        elif kind == "open_interest":
            points = data.get("points") or []
            if points:
                self.oi[symbol] = list(points)

    def _trade(self, symbol: str, timestamp: int, data: dict[str, Any]) -> None:
        price = _num(data.get("price"))
        size = _num(data.get("size")) or 0.0
        if not price:
            return
        self._touch_price(symbol, price)
        side = data.get("side")
        delta = size if side == "Buy" else -size
        self._cvd_value[symbol] = self._cvd_value.get(symbol, 0.0) + delta
        series = self.cvd.setdefault(symbol, [])
        series.append({"time": timestamp, "value": self._cvd_value[symbol]})
        del series[:-180]
        if side == "Buy":
            self.taker_buy[symbol] = self.taker_buy.get(symbol, 0.0) + size
        elif side == "Sell":
            self.taker_sell[symbol] = self.taker_sell.get(symbol, 0.0) + size
        closes = self.mini.setdefault(symbol, [])
        closes.append(price)
        del closes[:-30]

    def _touch_price(self, symbol: str, price: float) -> None:
        signal = self.signals.get(symbol)
        if signal is None:
            return
        signal["last_price"] = price
        entry = signal.get("entry_price")
        if entry:
            signal["pnl_pct"] = short_pnl_pct(float(entry), price)

    def _book(self, symbol: str, data: dict[str, Any]) -> None:
        book = self.books.setdefault(symbol, {"bids": {}, "asks": {}, "walls": []})
        if data.get("reset") or data.get("kind") == "snapshot":
            book["bids"] = {}
            book["asks"] = {}
        previous = {**book["bids"], **book["asks"]}
        for side_key, store_key in (("bids", "bids"), ("asks", "asks")):
            for row in data.get(side_key) or []:
                if len(row) < 2:
                    continue
                price = _num(row[0])
                size = _num(row[1])
                if price is None or size is None:
                    continue
                if size == 0:
                    book[store_key].pop(price, None)
                else:
                    book[store_key][price] = size
        book["walls"] = _walls(book["bids"], book["asks"], previous)
        ages = self._book_age.setdefault(symbol, {})
        for price in list(book["bids"]) + list(book["asks"]):
            ages[price] = ages.get(price, 0) + 1
        for price in list(ages):
            if price not in book["bids"] and price not in book["asks"]:
                ages.pop(price, None)

    def _obv(self, symbol: str) -> list[dict[str, float]]:
        candles = self.klines.get((symbol, "1"), [])
        if len(candles) < 2:
            return []
        value = 0.0
        series = []
        previous = float(candles[0]["close"])
        for candle in candles[1:]:
            close = float(candle["close"])
            volume = float(candle.get("volume") or 0)
            if close > previous:
                value += volume
            elif close < previous:
                value -= volume
            series.append({"time": candle["timestamp"], "value": value})
            previous = close
        return _trim_time_window(series, "time")


def _walls(
    bids: dict[float, float],
    asks: dict[float, float],
    previous: dict[float, float],
) -> list[dict[str, Any]]:
    sizes = list(bids.values()) + list(asks.values())
    if not sizes:
        return []
    sizes_sorted = sorted(sizes)
    median = sizes_sorted[len(sizes_sorted) // 2]
    large = max(median * 3, 0.0001)
    walls = []
    current = {**bids, **asks}
    for price, size in list(bids.items()) + list(asks.items()):
        old = previous.get(price, 0.0)
        side = "bid" if price in bids else "ask"
        if old >= large and size == 0:
            continue
        if size >= large and old == 0:
            kind = "building"
        elif old > 0 and size >= old * 1.3 and size >= large * 0.5:
            kind = "building"
        elif size >= large:
            kind = "holding"
        else:
            continue
        walls.append({"price": price, "side": side, "kind": kind, "size": size})
    for price, old in previous.items():
        if old >= large and price not in current:
            side = "bid" if price in previous and price not in asks else "ask"
            # Сторона исчезнувшего уровня неизвестна точно: рисуем как Spoof.
            walls.append({"price": price, "side": side, "kind": "spoof", "size": old})
    return walls[:12]


def _num(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
