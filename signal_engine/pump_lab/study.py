"""Широкий журнал пампа: сырые показатели на пике, на остановке и на старте снижения.

Числа только измеряются. Пороги входа сюда не входят: их подберём по накопленному журналу.
Поля, для которых нет потока (доля лонг-счетов, rush orders по миллисекундам, держатели, DEX),
пишутся как null, чтобы форма записи не менялась, когда поток появится.
"""

from __future__ import annotations

from typing import Any

from signal_engine.flow import oi_change_pct
from signal_engine.indicators import ema
from signal_engine.state import SymbolState

MIN_MS = 60_000

# Ключ → подпись. Порядок — порядок записи в журнал.
STUDY_FIELDS: tuple[tuple[str, str], ...] = (
    ("price", "Цена"),
    ("drawdown_pct", "Откат от пика, %"),
    ("since_peak_min", "Минут с пика"),
    ("growth_pct", "Рост дно→пик, %"),
    ("price_5m_pct", "Цена за 5 мин, %"),
    ("price_15m_pct", "Цена за 15 мин, %"),
    ("price_20m_pct", "Цена за 20 мин, %"),
    ("price_1h_pct", "Цена за 1 ч, %"),
    ("range_pct", "Ширина диапазона с пика, %"),
    ("lower_closes", "Подряд более низких закрытий"),
    ("volume_ratio_20m", "Объём 20 мин / пик такого окна"),
    ("red_bar_volume_ratio", "Объём последней красной минуты / средние 20"),
    ("buy_share_5m", "Доля агрессивных покупок 5 мин, %"),
    ("buy_share_10m", "Доля агрессивных покупок 10 мин, %"),
    ("buy_share_15m", "Доля агрессивных покупок 15 мин, %"),
    ("buys_fade_ratio", "Покупки 15 мин / пик 15 мин за 3 ч"),
    ("sell_windows_over_50", "Окон 5/10/15 мин с продажами > 50%"),
    ("cvd_5m_usd", "Дельта 5 мин, USD"),
    ("cvd_15m_usd", "Дельта 15 мин, USD"),
    ("tape_minutes_5m", "Минут ленты за 5 мин"),
    ("large_buy_15m_usd", "Крупные покупки 15 мин, USD"),
    ("large_sell_15m_usd", "Крупные продажи 15 мин, USD"),
    ("oi_chg_15m_pct", "OI за 15 мин, %"),
    ("oi_chg_1h_pct", "OI за 1 ч, %"),
    ("oi_chg_4h_pct", "OI за 4 ч, %"),
    ("price_up_oi_down", "Цена вверх и OI вниз (1/0)"),
    ("price_down_oi_down", "Цена вниз и OI вниз (1/0)"),
    ("price_down_oi_up", "Цена вниз и OI вверх (1/0)"),
    ("funding_rate", "Funding"),
    ("premium_pct", "Премия mark к index, %"),
    ("long_liq_5m_usd", "Ликвидации лонгов 5 мин, USD"),
    ("long_liq_15m_usd", "Ликвидации лонгов 15 мин, USD"),
    ("short_liq_5m_usd", "Ликвидации шортов 5 мин, USD"),
    ("short_liq_15m_usd", "Ликвидации шортов 15 мин, USD"),
    ("short_liq_fade_15m", "Затухание ликвидаций шортов, доля"),
    ("long_minus_short_liq_15m", "Лонги минус шорты, ликвидации 15 мин"),
    ("btc_15m_pct", "BTC за 15 мин, %"),
    ("btc_1h_pct", "BTC за 1 ч, %"),
    ("btc_4h_pct", "BTC за 4 ч, %"),
    ("alt_minus_btc_15m", "Монета минус BTC, 15 мин, п.п."),
    ("alt_minus_btc_1h", "Монета минус BTC, 1 ч, п.п."),
    ("close_vs_ema50_15m_pct", "Закрытие 15м против EMA50, %"),
    ("spread_pct", "Спред стакана, %"),
    ("imbalance_1pct", "Дисбаланс стакана ±1%: (bid−ask)/(bid+ask)"),
    ("bid_usd_1pct", "Биды в 1% под ценой, USD"),
    ("ask_usd_1pct", "Аски в 1% над ценой, USD"),
    ("thin_bid_ratio", "Биды 1% / аски 1%"),
    ("sell_slip_10k_pct", "Проскальзывание продажи $10k, %"),
    ("long_account_ratio", "Доля лонг-счетов"),
    ("rush_orders", "Rush orders, штук"),
    ("holder_top10_pct", "Доля топ-10 держателей, %"),
    ("dex_volume_to_liq", "Объём DEX / ликвидность"),
)


def build_study(
    state: SymbolState,
    btc: SymbolState | None,
    peak_price: float,
    peak_ts: int,
    now_ms: int,
    growth_pct: float | None = None,
) -> dict[str, float | None]:
    """Плоский набор чисел. Нет данных — null, не ноль."""
    price = float(state.last_price or 0) or None
    out: dict[str, float | None] = {key: None for key, _ in STUDY_FIELDS}
    out["price"] = price
    out["growth_pct"] = growth_pct
    if price and peak_price > 0:
        out["drawdown_pct"] = max(0.0, (1.0 - price / peak_price) * 100.0)
    if peak_ts:
        out["since_peak_min"] = max(0.0, (now_ms - peak_ts) / MIN_MS)

    out["price_5m_pct"] = _price_change(state, now_ms, 5)
    out["price_15m_pct"] = _price_change(state, now_ms, 15)
    out["price_20m_pct"] = _price_change(state, now_ms, 20)
    out["price_1h_pct"] = _price_change(state, now_ms, 60)
    out["range_pct"] = _range_since_peak(state, peak_ts, now_ms)
    out["lower_closes"] = _lower_closes(state)
    out["volume_ratio_20m"] = _volume_ratio(state, 20)
    out["red_bar_volume_ratio"] = _red_bar_volume(state)

    b5, s5 = _flow(state, now_ms, 5)
    b10, s10 = _flow(state, now_ms, 10)
    b15, s15 = _flow(state, now_ms, 15)
    out["buy_share_5m"] = _share(b5, s5)
    out["buy_share_10m"] = _share(b10, s10)
    out["buy_share_15m"] = _share(b15, s15)
    out["buys_fade_ratio"] = _buys_fade(state, now_ms)
    shares = [out["buy_share_5m"], out["buy_share_10m"], out["buy_share_15m"]]
    known = [v for v in shares if v is not None]
    if known:
        out["sell_windows_over_50"] = float(sum(1 for v in known if (100.0 - v) > 50.0))
    out["cvd_5m_usd"] = _sub(b5, s5)
    out["cvd_15m_usd"] = _sub(b15, s15)
    out["tape_minutes_5m"] = _tape_minutes(state, now_ms, 5)
    large_buy, large_sell = _large_flow(state, now_ms)
    out["large_buy_15m_usd"] = large_buy
    out["large_sell_15m_usd"] = large_sell

    points = state.oi_points()
    out["oi_chg_15m_pct"] = oi_change_pct(points, lookback_min=15)
    out["oi_chg_1h_pct"] = oi_change_pct(points, lookback_min=60)
    out["oi_chg_4h_pct"] = oi_change_pct(points, lookback_min=240)
    _oi_price_flags(out)

    out["funding_rate"] = state.funding_rate
    if state.mark_price and state.index_price and state.index_price > 0:
        out["premium_pct"] = (state.mark_price / state.index_price - 1.0) * 100.0

    out["long_liq_5m_usd"] = _bucket_sum(state.liq_long_notional, now_ms, 5)
    out["long_liq_15m_usd"] = _bucket_sum(state.liq_long_notional, now_ms, 15)
    out["short_liq_5m_usd"] = _short_liq(state, now_ms, 5)
    out["short_liq_15m_usd"] = _short_liq(state, now_ms, 15)
    out["short_liq_fade_15m"] = _short_fade(state, now_ms)
    if out["long_liq_15m_usd"] is not None and out["short_liq_15m_usd"] is not None:
        out["long_minus_short_liq_15m"] = out["long_liq_15m_usd"] - out["short_liq_15m_usd"]

    if btc is not None:
        out["btc_15m_pct"] = _price_change(btc, now_ms, 15)
        out["btc_1h_pct"] = _price_change(btc, now_ms, 60)
        out["btc_4h_pct"] = _price_change(btc, now_ms, 240)
        if out["price_15m_pct"] is not None and out["btc_15m_pct"] is not None:
            out["alt_minus_btc_15m"] = out["price_15m_pct"] - out["btc_15m_pct"]
        if out["price_1h_pct"] is not None and out["btc_1h_pct"] is not None:
            out["alt_minus_btc_1h"] = out["price_1h_pct"] - out["btc_1h_pct"]

    out["close_vs_ema50_15m_pct"] = _ema_gap(state)
    _book(state, out)
    return {key: _round(out[key]) for key, _ in STUDY_FIELDS}


def _oi_price_flags(out: dict[str, float | None]) -> None:
    price = out.get("price_15m_pct")
    oi = out.get("oi_chg_15m_pct")
    if price is None or oi is None:
        return
    out["price_up_oi_down"] = 1.0 if price > 0 and oi < 0 else 0.0
    out["price_down_oi_down"] = 1.0 if price < 0 and oi < 0 else 0.0
    out["price_down_oi_up"] = 1.0 if price < 0 and oi > 0 else 0.0


def _price_change(state: SymbolState, now_ms: int, minutes: int) -> float | None:
    bars = state.bars_1m
    if not bars or not state.last_price:
        return None
    target = now_ms - minutes * MIN_MS
    ref = None
    for bar in bars:
        if bar.timestamp <= target:
            ref = bar.close
        else:
            break
    if ref is None or ref <= 0:
        return None
    return (float(state.last_price) / ref - 1.0) * 100.0


def _range_since_peak(state: SymbolState, peak_ts: int, now_ms: int) -> float | None:
    if not peak_ts:
        return None
    start = max(peak_ts, now_ms - 120 * MIN_MS)
    bars = [b for b in state.bars_1m if b.timestamp >= start]
    if not bars:
        return None
    hi = max(b.high for b in bars)
    lo = min(b.low for b in bars)
    if hi <= 0:
        return None
    return (hi - lo) / hi * 100.0


def _lower_closes(state: SymbolState) -> float | None:
    closes = [b.close for b in state.bars_1m if b.close > 0]
    if len(closes) < 2:
        return None
    streak = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] < closes[i - 1]:
            streak += 1
        else:
            break
    return float(streak)


def _volume_ratio(state: SymbolState, window: int) -> float | None:
    bars = state.bars_1m[:-1] if len(state.bars_1m) > window * 2 else state.bars_1m
    if len(bars) < window * 2:
        return None
    volumes = [b.volume for b in bars]
    recent = sum(volumes[-window:]) / window
    running = sum(volumes[:window])
    best = running
    for i in range(window, len(volumes)):
        running += volumes[i] - volumes[i - window]
        best = max(best, running)
    peak = best / window
    if peak <= 0:
        return None
    return recent / peak


def _red_bar_volume(state: SymbolState) -> float | None:
    closed = state.bars_1m[:-1]
    if len(closed) < 21:
        return None
    last = closed[-1]
    if last.close >= last.open:
        return None
    base = [b.volume for b in closed[-21:-1]]
    avg = sum(base) / len(base)
    if avg <= 0:
        return None
    return last.volume / avg


def _minute_price(state: SymbolState, minute: int) -> float:
    for bar in state.bars_1m:
        if bar.timestamp == minute and bar.close > 0:
            return bar.close
    return float(state.last_price or 0)


def _usd(state: SymbolState, minute: int, qty: float) -> float:
    return qty * _minute_price(state, minute)


def _flow(state: SymbolState, now_ms: int, minutes: int) -> tuple[float, float]:
    """Агрессивные покупки и продажи в USD. В ленте size — базовый объём."""
    start = now_ms - minutes * MIN_MS
    buy = sum(_usd(state, ts, qty) for ts, qty in state.taker_buy.items() if ts >= start)
    sell = sum(_usd(state, ts, qty) for ts, qty in state.taker_sell.items() if ts >= start)
    return buy, sell


def _share(buy: float, sell: float) -> float | None:
    total = buy + sell
    if total <= 0:
        return None
    return buy / total * 100.0


def _sub(buy: float, sell: float) -> float | None:
    if buy == 0 and sell == 0:
        return None
    return buy - sell


def _buys_fade(state: SymbolState, now_ms: int) -> float | None:
    current = (now_ms // MIN_MS) * MIN_MS
    start = current - 179 * MIN_MS
    series = [state.taker_buy.get(start + i * MIN_MS, 0.0) for i in range(180)]
    if sum(series) <= 0:
        return None
    best = running = 0.0
    window = 15
    for i, value in enumerate(series):
        running += value
        if i >= window:
            running -= series[i - window]
        best = max(best, running)
    last = sum(series[-window:])
    if best <= 0:
        return None
    return last / best


def _tape_minutes(state: SymbolState, now_ms: int, minutes: int) -> float | None:
    start = now_ms - minutes * MIN_MS
    keys = {ts for ts in state.taker_buy if ts >= start} | {ts for ts in state.taker_sell if ts >= start}
    if not keys and not state.taker_buy and not state.taker_sell:
        return None
    return float(len(keys))


def _large_flow(state: SymbolState, now_ms: int) -> tuple[float | None, float | None]:
    vols = state.volumes_1m()
    if len(vols) < 20:
        return None, None
    med = sum(vols[-20:]) / 20.0
    if med <= 0:
        return None, None
    start = now_ms - 15 * MIN_MS
    buy = sum(_usd(state, ts, v) for ts, v in state.taker_buy.items() if ts >= start and v > med * 3)
    sell = sum(_usd(state, ts, v) for ts, v in state.taker_sell.items() if ts >= start and v > med * 3)
    return buy, sell


def _bucket_sum(bucket: dict[int, float], now_ms: int, minutes: int) -> float | None:
    if not bucket:
        return None
    start = now_ms - minutes * MIN_MS
    return sum(v for ts, v in bucket.items() if ts >= start)


def _short_liq(state: SymbolState, now_ms: int, minutes: int) -> float | None:
    """liq_notional — уже только ликвидации шортов (сторона Sell)."""
    return _bucket_sum(state.liq_notional, now_ms, minutes)


def _short_fade(state: SymbolState, now_ms: int) -> float | None:
    start = now_ms - 14 * MIN_MS
    series = [state.liq_notional.get(start + i * MIN_MS, 0.0) for i in range(15)]
    peak = max(series) if series else 0.0
    if peak <= 0:
        return None
    return 1.0 - max(series[-2:]) / peak


def _ema_gap(state: SymbolState) -> float | None:
    bars = state.bars_htf.get("15") or []
    closes = [b.close for b in bars if b.close > 0]
    if len(closes) < 50:
        return None
    series = ema(closes, 50)
    value = series[-1] if series else None
    if value is None or value <= 0:
        return None
    return (closes[-1] / value - 1.0) * 100.0


def _book(state: SymbolState, out: dict[str, Any]) -> None:
    bids = state.book_bids
    asks = state.book_asks
    if not bids or not asks:
        if state.bid1_price and state.ask1_price and state.ask1_price > 0:
            mid = (state.bid1_price + state.ask1_price) / 2.0
            if mid > 0:
                out["spread_pct"] = (state.ask1_price - state.bid1_price) / mid * 100.0
        return
    best_bid = max(bids)
    best_ask = min(asks)
    if best_bid <= 0 or best_ask <= 0:
        return
    mid = (best_bid + best_ask) / 2.0
    out["spread_pct"] = (best_ask - best_bid) / mid * 100.0
    bid_usd = sum(price * size for price, size in bids.items() if price >= mid * 0.99)
    ask_usd = sum(price * size for price, size in asks.items() if price <= mid * 1.01)
    out["bid_usd_1pct"] = bid_usd
    out["ask_usd_1pct"] = ask_usd
    if bid_usd + ask_usd > 0:
        out["imbalance_1pct"] = (bid_usd - ask_usd) / (bid_usd + ask_usd)
    if ask_usd > 0:
        out["thin_bid_ratio"] = bid_usd / ask_usd
    out["sell_slip_10k_pct"] = _sell_slip(bids, 10_000.0)


def _sell_slip(bids: dict[float, float], notional: float) -> float | None:
    left = notional
    cost = 0.0
    qty = 0.0
    for price in sorted(bids, reverse=True):
        level = price * bids[price]
        if level <= 0 or price <= 0:
            continue
        take = min(left, level)
        cost += take
        qty += take / price
        left -= take
        if left <= 1e-6:
            break
    if qty <= 0 or cost < notional * 0.5:
        return None
    avg = cost / qty
    best = max(bids)
    if best <= 0:
        return None
    return (best - avg) / best * 100.0


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)
