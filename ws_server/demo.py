"""Пример доски, если Redis ещё не запущен.

Это не рынок и не сигнал к входу. Баннер на странице об этом говорит.
Как только приходит живая доска, пример выключается.
"""

from __future__ import annotations

from typing import Any


def demo_board() -> list[dict[str, Any]]:
    specs = [
        ("BEAMUSDT", 5, 128.0, 78.0, 0.0284, 0.0271, True),
        ("WIFUSDT", 4, 96.0, 64.0, 1.42, 1.39, False),
        ("MEMEUSDT", 3, 74.0, 55.0, 0.018, 0.0176, False),
        ("DOGEUSDT", 2, 51.0, 48.0, 0.121, 0.119, False),
        ("NOTUSDT", 1, 33.0, 42.0, 0.0072, 0.0074, False),
    ]
    columns = {
        5: {"strength": 5, "color": "green", "status": "ВХОД", "label": "5/5", "signals": []},
        4: {"strength": 4, "color": "orange", "status": "ПОЧТИ ГОТОВ", "label": "4/5", "signals": []},
        3: {"strength": 3, "color": "yellow", "status": "ОЖИДАНИЕ", "label": "3/5", "signals": []},
        2: {"strength": 2, "color": "blue", "status": "ФОРМИРОВАНИЕ", "label": "2/5", "signals": []},
        1: {"strength": 1, "color": "gray", "status": "НАБЛЮДЕНИЕ", "label": "1/5", "signals": []},
    }
    names = ("pump", "liquidations_faded", "oi_drop", "volume_faded", "sweep")
    for symbol, strength, rating, probability, entry, last, rich in specs:
        checks = {name: index < strength for index, name in enumerate(names)}
        signal = {
            "id": strength,
            "symbol": symbol,
            "created_at": 1_700_100_000_000,
            "updated_at": 1_700_100_300_000,
            "entry_price": entry,
            "last_price": last,
            "strength": strength,
            "rating": rating,
            "probability": probability,
            "quality": 2 if strength >= 4 else 1,
            "tf_match": 2 if strength == 5 else 1 if strength >= 3 else 0,
            "extra": 3 if strength == 5 else 1,
            "color": columns[strength]["color"],
            "status": columns[strength]["status"],
            "label": columns[strength]["label"],
            "checks": checks,
            "extras": {
                "cvd_divergence": strength >= 4,
                "taker_seller": strength >= 3,
                "obv_divergence": strength >= 5,
                "funding_extreme": strength >= 5,
                "round_level": strength >= 2,
            },
            "price_change_5m": 1.2,
            "price_change_15m": 6.4,
            "volume_ratio": 6.2,
            "rsi": 72.0,
            "oi_change_pct": -1.8 if checks["oi_drop"] else 0.4,
            "sweep_timeframes": ["4H", "1D"] if strength == 5 else ["1H"] if checks["sweep"] else [],
            "mega_level": strength == 5,
            "taker_ratio": 0.82 if strength >= 3 else 1.3,
            "funding_rate": 0.0012 if strength >= 5 else 0.0001,
            "outcome": None,
            "pnl_pct": ((entry - last) / entry) * 100 * 10 if strength == 5 else None,
            "chart_levels": [
                {"price": entry * 1.04, "kind": "strong", "timeframe": "4H", "swept": True},
                {"price": entry * 1.08, "kind": "medium", "timeframe": "1D", "swept": False},
            ]
            if rich
            else [],
            "round_prices": [round(entry, 4), round(entry * 1.05, 4)] if rich else [],
        }
        columns[strength]["signals"].append(signal)
    return [columns[level] for level in (5, 4, 3, 2, 1)]


def demo_market(cache_columns: list[dict[str, Any]]) -> dict[str, Any]:
    """Свечи, стакан, ликвидации и индикаторы для примерной карточки BEAMUSDT."""
    beam = cache_columns[0]["signals"][0]
    entry = float(beam["entry_price"])
    klines: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for column in cache_columns:
        for signal in column["signals"]:
            symbol = str(signal["symbol"])
            price = float(signal["entry_price"])
            klines[(symbol, "1")] = _candles(price * 0.94, 60, 60_000, 0.0011)
            klines[(symbol, "5")] = _candles(price * 0.9, 48, 300_000, 0.002)
            klines[(symbol, "15")] = _candles(price * 0.88, 40, 900_000, 0.003)
            klines[(symbol, "60")] = _candles(price * 0.8, 48, 3_600_000, 0.004)
            klines[(symbol, "240")] = _candles(price * 0.7, 40, 14_400_000, 0.006)
            klines[(symbol, "D")] = _candles(price * 0.55, 30, 86_400_000, 0.01)
    candles_1m = klines[("BEAMUSDT", "1")]
    return {
        "klines": klines,
        "book": {
            "bids": [[round(entry * (1 - 0.004 * i), 6), 800 if i == 3 else 120 + i * 15] for i in range(1, 13)],
            "asks": [[round(entry * (1 + 0.004 * i), 6), 1400 if i == 2 else 100 + i * 20] for i in range(1, 13)],
            "walls": [
                {"price": round(entry * (1 - 0.012), 6), "side": "bid", "kind": "holding", "size": 800},
                {"price": round(entry * (1 + 0.008), 6), "side": "ask", "kind": "building", "size": 1400},
                {"price": round(entry * (1 + 0.02), 6), "side": "ask", "kind": "spoof", "size": 2200},
            ],
        },
        "liquidations": _liquidations(candles_1m),
        "oi": _falling_series(candles_1m, 1_200_000, -0.004),
        "cvd": _falling_series(candles_1m, 0, -40),
        "funding": 0.0012,
    }


def demo_stats() -> dict[str, Any]:
    equity = [100, 108, 121, 117, 126, 119, 132, 128, 141]
    return {
        "win_rate": 62.0,
        "profit_factor": 1.8,
        "avg_return": 1.4,
        "max_drawdown": 18.0,
        "count": 12,
        "equity": equity,
        "rows": [
            {"symbol": "BEAMUSDT", "status": "ВХОД", "outcome": "TP_HIT", "pnl_pct": 32.0, "rating": 128, "created_at": 1_700_090_000_000, "entry_price": 0.021},
            {"symbol": "WIFUSDT", "status": "ПОЧТИ ГОТОВ", "outcome": "LIQUIDATED", "pnl_pct": -40.0, "rating": 90, "created_at": 1_700_080_000_000, "entry_price": 1.1},
            {"symbol": "MEMEUSDT", "status": "ОЖИДАНИЕ", "outcome": "TIME_EXIT", "pnl_pct": 4.0, "rating": 70, "created_at": 1_700_070_000_000, "entry_price": 0.012},
        ],
        "demo": True,
    }


def _candles(start: float, count: int, step_ms: int, drift: float) -> list[dict[str, Any]]:
    candles = []
    price = start
    timestamp = 1_700_000_000_000
    for index in range(count):
        open_ = price
        # В конце рост выдыхается: так на графике виден памп и остановка.
        local = drift if index < count * 0.75 else -drift * 0.35
        price = max(price * (1 + local), start * 0.5)
        high = max(open_, price) * 1.006
        low = min(open_, price) * 0.994
        if index == int(count * 0.7):
            high = price * 1.03
        candles.append(
            {
                "timestamp": timestamp + index * step_ms,
                "open": round(open_, 8),
                "high": round(high, 8),
                "low": round(low, 8),
                "close": round(price, 8),
                "volume": 1000 + (index % 7) * 180,
            }
        )
    return candles


def _liquidations(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points = []
    for index, candle in enumerate(candles[-24:]):
        # К концу окна объём меньше — на карте это затухание.
        size = max(4.0, 40 - index * 1.5)
        points.append({"time": candle["timestamp"], "price": candle["high"], "size": size})
    return points


def _falling_series(candles: list[dict[str, Any]], start: float, step: float) -> list[dict[str, Any]]:
    series = []
    value = start
    for candle in candles[-30:]:
        value += step
        series.append({"time": candle["timestamp"], "value": round(value, 4)})
    return series
