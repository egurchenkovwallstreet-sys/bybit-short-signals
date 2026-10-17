"""Память по одному символу: бары, ликвидации, CVD и OI.

Объём минутного бара берётся из свечи биржи. Сделки обновляют цену
и отдельно копят CVD, но не прибавляются к объёму свечи второй раз.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from signal_engine.levels import Candle
from signal_engine.liquidations import is_short_liquidation, minute_start


@dataclass
class Bar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    from_kline: bool = False

    def as_candle(self) -> Candle:
        return Candle(self.timestamp, self.open, self.high, self.low, self.close, self.volume)


@dataclass
class SymbolState:
    symbol: str
    bars_1m: list[Bar] = field(default_factory=list)
    bars_htf: dict[str, list[Bar]] = field(default_factory=dict)
    oi_5m: list[tuple[int, float]] = field(default_factory=list)
    ticker_oi: float | None = None
    ticker_oi_ts: int | None = None
    liq_notional: dict[int, float] = field(default_factory=dict)
    liq_long_notional: dict[int, float] = field(default_factory=dict)
    cvd_delta: dict[int, float] = field(default_factory=dict)
    taker_buy: dict[int, float] = field(default_factory=dict)
    taker_sell: dict[int, float] = field(default_factory=dict)
    last_price: float | None = None
    funding_rate: float | None = None
    mark_price: float | None = None
    index_price: float | None = None
    bid1_price: float | None = None
    ask1_price: float | None = None
    turnover_24h_usdt: float | None = None
    price_24h_change: float | None = None
    book_bids: dict[float, float] = field(default_factory=dict)
    book_asks: dict[float, float] = field(default_factory=dict)
    book_ts: int | None = None

    def ingest(self, message: dict) -> None:
        kind = message.get("type")
        data = message.get("data") or {}
        timestamp = int(message.get("timestamp") or 0)
        if kind == "trade":
            self._trade(timestamp, data)
        elif kind == "liquidation":
            self._liquidation(timestamp, data)
        elif kind == "ticker":
            self._ticker(timestamp, data)
        elif kind == "open_interest":
            self._oi(data)
        elif kind == "kline":
            self._klines(data)
        elif kind == "orderbook":
            self._orderbook(timestamp, data)

    def closes_1m(self) -> list[float]:
        return [bar.close for bar in self.bars_1m]

    def volumes_1m(self) -> list[float]:
        return [bar.volume for bar in self.bars_1m]

    def oi_points(self) -> list[tuple[int, float]]:
        points = list(self.oi_5m)
        if self.ticker_oi is not None and self.ticker_oi_ts is not None:
            if not points or self.ticker_oi_ts > points[-1][0]:
                points.append((self.ticker_oi_ts, self.ticker_oi))
        return points

    def htf_candles(self, interval: str) -> list[Candle]:
        return [bar.as_candle() for bar in self.bars_htf.get(interval, [])]

    def _trade(self, timestamp: int, data: dict) -> None:
        price = _float(data.get("price"))
        size = _float(data.get("size"))
        if price is None or size is None or price <= 0 or size < 0:
            return
        self.last_price = price
        minute = minute_start(timestamp)
        self._touch_bar(minute, price, size)
        side = data.get("side")
        if side == "Buy":
            self.cvd_delta[minute] = self.cvd_delta.get(minute, 0.0) + size
            self.taker_buy[minute] = self.taker_buy.get(minute, 0.0) + size
        elif side == "Sell":
            self.cvd_delta[minute] = self.cvd_delta.get(minute, 0.0) - size
            self.taker_sell[minute] = self.taker_sell.get(minute, 0.0) + size
        self._trim_buckets(timestamp)

    def _touch_bar(self, minute: int, price: float, size: float) -> None:
        if self.bars_1m and self.bars_1m[-1].timestamp == minute:
            bar = self.bars_1m[-1]
            bar.high = max(bar.high, price)
            bar.low = min(bar.low, price)
            bar.close = price
            if not bar.from_kline:
                bar.volume += size
            return
        self.bars_1m.append(
            Bar(minute, price, price, price, price, size, from_kline=False)
        )
        self.bars_1m = self.bars_1m[-config.BAR_HISTORY_LIMIT :]

    def _liquidation(self, timestamp: int, data: dict) -> None:
        side = data.get("side")
        price = _float(data.get("price"))
        size = _float(data.get("size"))
        if price is None or size is None or price <= 0 or size <= 0:
            return
        minute = minute_start(timestamp)
        notional = price * size
        if is_short_liquidation(side):
            self.liq_notional[minute] = self.liq_notional.get(minute, 0.0) + notional
        elif side == "Buy":
            self.liq_long_notional[minute] = self.liq_long_notional.get(minute, 0.0) + notional
        else:
            return
        self._trim_buckets(timestamp)

    def _ticker(self, timestamp: int, data: dict) -> None:
        price = _float(data.get("last_price"))
        if price is not None and price > 0:
            self.last_price = price
        if "funding_rate" in data:
            rate = _float(data.get("funding_rate"))
            if rate is not None:
                self.funding_rate = rate
        oi = _float(data.get("open_interest"))
        if oi is not None:
            self.ticker_oi = oi
            self.ticker_oi_ts = timestamp
        turnover = _float(data.get("turnover_24h"))
        if turnover is not None and turnover >= 0:
            self.turnover_24h_usdt = turnover
        change = _float(data.get("price_24h_change"))
        if change is not None:
            self.price_24h_change = change
        mark = _float(data.get("mark_price"))
        if mark is not None and mark > 0:
            self.mark_price = mark
        index = _float(data.get("index_price"))
        if index is not None and index > 0:
            self.index_price = index
        bid1 = _float(data.get("bid1_price"))
        if bid1 is not None and bid1 > 0:
            self.bid1_price = bid1
        ask1 = _float(data.get("ask1_price"))
        if ask1 is not None and ask1 > 0:
            self.ask1_price = ask1

    def _orderbook(self, timestamp: int, data: dict) -> None:
        """Снимок или дельта стакана. size = 0 снимает уровень."""
        if data.get("reset"):
            self.book_bids.clear()
            self.book_asks.clear()
        _apply_book(self.book_bids, data.get("bids") or [])
        _apply_book(self.book_asks, data.get("asks") or [])
        if timestamp:
            self.book_ts = timestamp
        _trim_book(self.book_bids, reverse=True)
        _trim_book(self.book_asks, reverse=False)

    def _oi(self, data: dict) -> None:
        # Для решения «OI падает» хватает 5-минуток. Остальные интервалы не мешают.
        if data.get("interval") not in (None, "5min"):
            return
        points = []
        for row in data.get("points") or []:
            ts = _int(row.get("timestamp"))
            value = _float(row.get("open_interest"))
            if ts is None or value is None:
                continue
            points.append((ts, value))
        if not points:
            return
        merged = {ts: value for ts, value in self.oi_5m}
        merged.update(points)
        self.oi_5m = sorted(merged.items())[-config.OI_FETCH_LIMIT :]

    def _klines(self, data: dict) -> None:
        interval = str(data.get("interval") or "")
        incoming = []
        for row in data.get("candles") or []:
            bar = _bar_from_candle(row)
            if bar is not None:
                incoming.append(bar)
        if not incoming:
            return
        if interval == "1":
            self.bars_1m = _merge_bars(self.bars_1m, incoming, config.BAR_HISTORY_LIMIT)
            self.last_price = self.bars_1m[-1].close
            return
        stored = (
            set(config.KLINE_INTERVALS)
            | set(config.HTF_INTERVALS)
            | set(config.PUMP_SCAN_EMA_INTERVALS)
        )
        stored.discard("1")
        if interval in stored:
            limit = config.LEVEL_LOOKBACK_CANDLES if interval in config.HTF_INTERVALS else config.BAR_HISTORY_LIMIT
            current = self.bars_htf.get(interval, [])
            self.bars_htf[interval] = _merge_bars(current, incoming, limit)

    def _trim_buckets(self, timestamp: int) -> None:
        cutoff = minute_start(timestamp) - 180 * 60_000
        for bucket in (self.liq_notional, self.liq_long_notional, self.cvd_delta, self.taker_buy, self.taker_sell):
            for key in list(bucket):
                if key < cutoff:
                    del bucket[key]


def _merge_bars(existing: list[Bar], incoming: list[Bar], limit: int) -> list[Bar]:
    by_ts = {bar.timestamp: bar for bar in existing}
    for bar in incoming:
        bar.from_kline = True
        by_ts[bar.timestamp] = bar
    merged = [by_ts[key] for key in sorted(by_ts)]
    return merged[-limit:]


def _bar_from_candle(row: dict) -> Bar | None:
    timestamp = _int(row.get("timestamp"))
    open_ = _float(row.get("open"))
    high = _float(row.get("high"))
    low = _float(row.get("low"))
    close = _float(row.get("close"))
    volume = _float(row.get("volume"))
    if None in (timestamp, open_, high, low, close, volume):
        return None
    return Bar(timestamp, open_, high, low, close, volume, from_kline=True)


def _apply_book(book: dict[float, float], levels: object) -> None:
    if not isinstance(levels, list):
        return
    for row in levels:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price = _float(row[0])
        size = _float(row[1])
        if price is None or price <= 0 or size is None:
            continue
        if size <= 0:
            book.pop(price, None)
        else:
            book[price] = size


def _trim_book(book: dict[float, float], reverse: bool, keep: int = 50) -> None:
    if len(book) <= keep + 30:
        return
    top = sorted(book, reverse=reverse)[:keep]
    kept = {price: book[price] for price in top}
    book.clear()
    book.update(kept)


def _float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
