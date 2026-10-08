"""Виртуальный изолированный шорт: ликвидация, трейлинг-стоп, комиссии, funding.

ROE — прибыль в % от маржи без комиссий: (вход − цена) / вход × плечо × 100.
Трейлинг: до ROE 100% стоп в 10% цены над лучшей ценой, к ROE 300% расстояние
плавно сужается до 2% цены и дальше держится.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config


def liquidation_price(entry: float, leverage: int | None = None, mmr: float | None = None) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    rate = config.PAPER_MAINT_MARGIN_RATE if mmr is None else mmr
    return entry * (1.0 + 1.0 / lev - rate)


def roe_pct(entry: float, price: float, leverage: int | None = None) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    if entry <= 0:
        return 0.0
    return (entry - price) / entry * lev * 100.0


def trail_distance_pct(best_roe: float) -> float:
    start = config.PAPER_TRAIL_START_DIST_PCT
    floor = config.PAPER_TRAIL_MIN_DIST_PCT
    lo = config.PAPER_TRAIL_TIGHTEN_FROM_ROE
    hi = config.PAPER_TRAIL_TIGHTEN_TO_ROE
    if best_roe <= lo:
        return start
    if best_roe >= hi:
        return floor
    share = (best_roe - lo) / (hi - lo)
    return start - (start - floor) * share


def trail_stop(entry: float, best_price: float, leverage: int | None = None) -> float:
    dist = trail_distance_pct(roe_pct(entry, best_price, leverage))
    return best_price * (1.0 + dist / 100.0)


@dataclass
class Position:
    """Общий счётчик для реальной виртуальной сделки и теневой (без баланса)."""

    symbol: str
    opened_at: int
    entry_price: float
    margin: float
    leverage: int = field(default_factory=lambda: config.PAPER_LEVERAGE)
    best_price: float = 0.0
    worst_price: float = 0.0
    stop_price: float = 0.0
    liq_price: float = 0.0
    entry_fee: float = 0.0
    funding_paid: float = 0.0
    next_funding_ts: int | None = None
    last_price: float = 0.0

    def __post_init__(self) -> None:
        if self.best_price <= 0:
            self.best_price = self.entry_price
        if self.worst_price <= 0:
            self.worst_price = self.entry_price
        if self.liq_price <= 0:
            self.liq_price = liquidation_price(self.entry_price, self.leverage)
        if self.entry_fee <= 0:
            self.entry_fee = self.notional * config.PAPER_FEE_RATE_TAKER
        if self.stop_price <= 0:
            self.stop_price = min(self.liq_price, trail_stop(self.entry_price, self.best_price, self.leverage))
        if self.last_price <= 0:
            self.last_price = self.entry_price

    @property
    def notional(self) -> float:
        return self.margin * self.leverage

    @property
    def qty(self) -> float:
        return self.notional / self.entry_price

    def gross_pnl(self, price: float) -> float:
        return (self.entry_price - price) * self.qty

    def exit_fee(self, price: float) -> float:
        return self.qty * price * config.PAPER_FEE_RATE_TAKER

    def net_pnl(self, price: float) -> float:
        return self.gross_pnl(price) - self.entry_fee - self.exit_fee(price) + self.funding_paid

    def net_roe(self, price: float) -> float:
        return self.net_pnl(price) / self.margin * 100.0 if self.margin > 0 else 0.0

    def max_roe(self) -> float:
        return roe_pct(self.entry_price, self.best_price, self.leverage)

    def min_roe(self) -> float:
        return roe_pct(self.entry_price, self.worst_price, self.leverage)

    def apply_funding(self, now_ms: int, rate: float | None, price: float) -> float:
        """Шорт получает funding при положительной ставке и платит при отрицательной."""
        if self.next_funding_ts is None or rate is None or now_ms < self.next_funding_ts:
            return 0.0
        payment = self.qty * price * rate
        self.funding_paid += payment
        self.next_funding_ts = None
        return payment

    def update(self, low: float, high: float, last: float) -> str | None:
        """Обновить по диапазону цен с прошлой проверки. Вернуть причину выхода."""
        self.last_price = last
        if high >= self.liq_price:
            self.worst_price = max(self.worst_price, self.liq_price)
            return "liquidation"
        if high >= self.stop_price:
            self.worst_price = max(self.worst_price, min(high, self.stop_price))
            return "trailing_stop"
        self.worst_price = max(self.worst_price, high)
        if low < self.best_price:
            self.best_price = low
            self.stop_price = min(self.liq_price, trail_stop(self.entry_price, low, self.leverage))
            if last >= self.stop_price:
                return "trailing_stop"
        return None

    def close_result(self, reason: str) -> dict:
        """Итог закрытия. Ликвидация списывает всю маржу и комиссию входа."""
        if reason == "liquidation":
            price = self.liq_price
            exit_fee = 0.0
            pnl = -self.margin - self.entry_fee + self.funding_paid
        else:
            price = self.stop_price
            exit_fee = self.exit_fee(price)
            pnl = self.gross_pnl(price) - self.entry_fee - exit_fee + self.funding_paid
        return {
            "exit_price": price,
            "exit_fee": exit_fee,
            "pnl_usd": pnl,
            "roe_pct": pnl / self.margin * 100.0 if self.margin > 0 else 0.0,
        }
