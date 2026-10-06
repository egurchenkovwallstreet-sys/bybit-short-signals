"""Вкладка «Поиск пампов»: быстрый (1–12 ч) и длинный (до 20 д), липкий список."""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.flow import oi_change_pct
from signal_engine.state import Bar, SymbolState
from signal_engine.swing_highs import closed_bars
from signal_engine.watch_store import WatchRow, WatchStore

BOARD_ID = "pump_strategy"

_MS_DAY = 24 * 3600 * 1000
_MS_HOUR = 3_600_000
_BAR_MS = {"1": 60_000, "5": 300_000, "15": 900_000, "60": 3_600_000, "240": 14_400_000, "D": 86_400_000}


@dataclass(frozen=True)
class PumpMatch:
    kind: str  # short | long
    growth_pct: float
    valley_price: float
    peak_price: float
    valley_ts: int
    peak_ts: int
    interval: str


def _meets_turnover(state: SymbolState) -> bool:
    turnover = state.turnover_24h_usdt
    if turnover is None:
        return False
    return turnover >= config.PUMP_STRATEGY_MIN_TURNOVER_24H_USDT


def _pick_bars_long(state: SymbolState) -> tuple[str, list[Bar]]:
    for key in ("D", "240", "60"):
        bars = state.bars_htf.get(key) or []
        if len(bars) >= 5:
            return key, bars
    return "", []


def _pick_bars_short(state: SymbolState) -> tuple[str, list[Bar]]:
    for key in ("5", "15", "1"):
        if key == "1":
            bars = state.bars_1m
        else:
            bars = state.bars_htf.get(key) or []
        if len(bars) >= 5:
            return key, bars
    return "", []


def _closed(bars: list[Bar], interval: str, now_ms: int) -> list[Bar]:
    if interval in _BAR_MS and interval not in ("60", "240", "D", "15", "30"):
        step = _BAR_MS[interval]
        if not bars:
            return []
        if len(bars) == 1:
            return bars if bars[0].timestamp + step <= now_ms else []
        out = [b for b in bars if b.timestamp + step <= now_ms]
        return out if out else bars[:-1]
    return closed_bars(bars, interval, now_ms)


def _match_from_window(
    window: list[Bar],
    *,
    kind: str,
    min_pct: float,
    min_duration_ms: int,
    max_duration_ms: int,
    interval: str,
) -> PumpMatch | None:
    if len(window) < 3:
        return None
    # Глобальный минимум и максимум в окне (пик мог быть до текущего отката).
    valley_bar = min(window, key=lambda b: b.low)
    peak_bar = max(window, key=lambda b: b.high)
    valley_price = float(valley_bar.low)
    peak_price = float(peak_bar.high)
    if valley_price <= 0 or peak_price <= 0:
        return None
    duration = abs(int(peak_bar.timestamp) - int(valley_bar.timestamp))
    if duration < min_duration_ms or duration > max_duration_ms:
        return None
    mult = peak_price / valley_price
    growth_pct = (mult - 1.0) * 100.0
    if kind == "long":
        if mult < config.PUMP_STRATEGY_LONG_MIN_MULTIPLIER:
            return None
    elif growth_pct < min_pct:
        return None
    return PumpMatch(
        kind=kind,
        growth_pct=growth_pct,
        valley_price=valley_price,
        peak_price=peak_price,
        valley_ts=int(valley_bar.timestamp),
        peak_ts=int(peak_bar.timestamp),
        interval=interval,
    )


def detect_short_pump(state: SymbolState, now_ms: int) -> PumpMatch | None:
    """Рост от минимума до максимума за 1–12 ч, порог SHORT_MIN_PCT."""
    if not _meets_turnover(state):
        return None
    interval, bars = _pick_bars_short(state)
    if not bars:
        return None
    window_ms = config.PUMP_STRATEGY_SHORT_HOURS_MAX * _MS_HOUR
    closed = _closed(bars, interval, now_ms)
    window = [b for b in closed if b.timestamp >= now_ms - window_ms]
    if len(window) < 3:
        return None
    min_d = config.PUMP_STRATEGY_SHORT_HOURS_MIN * _MS_HOUR
    max_d = config.PUMP_STRATEGY_SHORT_HOURS_MAX * _MS_HOUR
    return _match_from_window(
        window,
        kind="short",
        min_pct=config.PUMP_STRATEGY_SHORT_MIN_PCT,
        min_duration_ms=min_d,
        max_duration_ms=max_d,
        interval=interval,
    )


def detect_long_pump(state: SymbolState, now_ms: int) -> PumpMatch | None:
    """Рост от минимума до максимума за окно до LONG_DAYS дней, порог LONG_MIN_PCT."""
    if not _meets_turnover(state):
        return None
    interval, bars = _pick_bars_long(state)
    if not bars:
        return None
    window_ms = config.PUMP_STRATEGY_LONG_DAYS * _MS_DAY
    closed = closed_bars(bars, interval, now_ms)
    window = [b for b in closed if b.timestamp >= now_ms - window_ms]
    if len(window) < 3:
        window = closed[-min(len(closed), config.PUMP_STRATEGY_LONG_DAYS + 1) :]
    if len(window) < 3:
        return None
    min_d = _MS_HOUR  # хотя бы ~1 ч между дном и пиком
    max_d = config.PUMP_STRATEGY_LONG_DAYS * _MS_DAY
    return _match_from_window(
        window,
        kind="long",
        min_pct=config.PUMP_STRATEGY_LONG_MIN_PCT,
        min_duration_ms=min_d,
        max_duration_ms=max_d,
        interval=interval,
    )


def detect_best_pump(state: SymbolState, now_ms: int) -> PumpMatch | None:
    """Если подходят оба типа — берём больший процент роста."""
    short = detect_short_pump(state, now_ms)
    long = detect_long_pump(state, now_ms)
    if short and long:
        return short if short.growth_pct >= long.growth_pct else long
    return short or long


def format_period_ru(valley_ts: int, peak_ts: int) -> str:
    """Человекочитаемая длительность между дном и пиком в окне."""
    if valley_ts == peak_ts:
        return "—"
    hours = max(1, int(round(abs(peak_ts - valley_ts) / _MS_HOUR)))
    if hours < 48:
        return f"{hours} ч"
    days = max(1, int(round(hours / 24)))
    return f"{days} д"


def _kind_label(kind: str) -> str:
    if kind == "short":
        return "Быстрый памп"
    if kind == "long":
        return "Длинный рост"
    return kind


def _oi_metrics(state: SymbolState) -> tuple[float | None, float | None, float | None]:
    points = state.oi_points()
    if not points:
        return None, None, None
    last_oi = float(points[-1][1])
    ch1 = oi_change_pct(points, lookback_min=60)
    ch4 = oi_change_pct(points, lookback_min=240)
    return ch1, ch4, last_oi


@dataclass
class PumpStrategyItem:
    symbol: str
    kind: str
    growth_pct: float
    period_label: str
    turnover_24h_usdt: float
    last_price: float
    oi_change_1h_pct: float | None
    oi_change_4h_pct: float | None
    oi_last: float | None
    valley_price: float
    peak_price: float
    updated_at: int

    def to_data(self) -> dict:
        return {
            "symbol": self.symbol,
            "kind": self.kind,
            "kind_label": _kind_label(self.kind),
            "growth_pct": round(self.growth_pct, 1),
            "period_label": self.period_label,
            "turnover_24h_usdt": self.turnover_24h_usdt,
            "last_price": self.last_price,
            "oi_change_1h_pct": _round_opt(self.oi_change_1h_pct),
            "oi_change_4h_pct": _round_opt(self.oi_change_4h_pct),
            "oi_last": self.oi_last,
            "valley_price": self.valley_price,
            "peak_price": self.peak_price,
            "updated_at": self.updated_at,
        }


def _round_opt(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _item_from_match(symbol: str, state: SymbolState, match: PumpMatch, now_ms: int) -> PumpStrategyItem:
    price = state.last_price or match.peak_price
    ch1, ch4, oi_last = _oi_metrics(state)
    return PumpStrategyItem(
        symbol=symbol,
        kind=match.kind,
        growth_pct=match.growth_pct,
        period_label=format_period_ru(match.valley_ts, match.peak_ts),
        turnover_24h_usdt=float(state.turnover_24h_usdt or 0),
        last_price=float(price),
        oi_change_1h_pct=ch1,
        oi_change_4h_pct=ch4,
        oi_last=oi_last,
        valley_price=match.valley_price,
        peak_price=match.peak_price,
        updated_at=now_ms,
    )


def _item_from_meta(symbol: str, state: SymbolState, meta: dict, now_ms: int) -> PumpStrategyItem | None:
    if state.last_price is None or state.last_price <= 0:
        return None
    growth = float(meta.get("growth_pct") or 0)
    ch1, ch4, oi_last = _oi_metrics(state)
    kind = str(meta.get("kind") or "long")
    return PumpStrategyItem(
        symbol=symbol,
        kind=kind,
        growth_pct=growth,
        period_label=str(meta.get("period_label") or "—"),
        turnover_24h_usdt=float(state.turnover_24h_usdt or 0),
        last_price=float(state.last_price),
        oi_change_1h_pct=ch1,
        oi_change_4h_pct=ch4,
        oi_last=oi_last,
        valley_price=float(meta.get("valley_price") or 0),
        peak_price=float(meta.get("peak_price") or 0),
        updated_at=now_ms,
    )


def _meta_from_match(match: PumpMatch) -> dict:
    return {
        "kind": match.kind,
        "growth_pct": match.growth_pct,
        "period_label": format_period_ru(match.valley_ts, match.peak_ts),
        "valley_price": match.valley_price,
        "peak_price": match.peak_price,
    }


def _refresh_match(state: SymbolState, now_ms: int, stored_kind: str) -> PumpMatch | None:
    """Обновление: сначала тот же тип, что при постановке на доску."""
    if stored_kind == "short":
        return detect_short_pump(state, now_ms) or detect_long_pump(state, now_ms)
    if stored_kind == "long":
        return detect_long_pump(state, now_ms) or detect_short_pump(state, now_ms)
    return detect_best_pump(state, now_ms)


def _should_exit(state: SymbolState | None) -> bool:
    if state is None:
        return True
    return not _meets_turnover(state)


def build_pump_strategy_board(states: dict[str, SymbolState], now_ms: int, watches: WatchStore) -> dict:
    active = watches.active(BOARD_ID)

    for symbol, state in states.items():
        if symbol in active:
            continue
        prior = watches.get(BOARD_ID, symbol)
        if prior is not None and prior.dismissed:
            continue
        match = detect_best_pump(state, now_ms)
        if match is None:
            continue
        watch = WatchRow(
            board=BOARD_ID,
            symbol=symbol,
            entered_at=now_ms,
            dismissed=False,
            confirmed_stage=1,
            pending_stage=None,
            pending_since=None,
            meta=_meta_from_match(match),
        )
        watches.upsert(watch)
        active[symbol] = watch

    items: list[PumpStrategyItem] = []
    for symbol, watch in list(active.items()):
        state = states.get(symbol)
        if _should_exit(state):
            watches.remove(BOARD_ID, symbol)
            continue
        assert state is not None
        stored_kind = str(watch.meta.get("kind") or "long")
        match = _refresh_match(state, now_ms, stored_kind)
        if match is not None:
            item = _item_from_match(symbol, state, match, now_ms)
            watch.meta = _meta_from_match(match)
            watches.upsert(watch)
        else:
            item = _item_from_meta(symbol, state, watch.meta, now_ms)
            if item is None:
                watches.remove(BOARD_ID, symbol)
                continue
        items.append(item)

    ordered = sorted(items, key=lambda row: (0 if row.kind == "short" else 1, -row.growth_pct))
    return {
        "type": "pump_strategy_board",
        "timestamp": now_ms,
        "data": {"signals": [row.to_data() for row in ordered]},
    }
