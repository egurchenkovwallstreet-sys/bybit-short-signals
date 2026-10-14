"""Виртуальный изолированный шорт: ликвидация, трейлинг-стоп, комиссии, funding.

ROE — прибыль в % от маржи без комиссий: (вход − цена) / вход × плечо × 100.
t20: при пике ≥ 3% стоп на +0.5% net, при ≥ 7% — не хуже +5%, дальше трейл «пик − 20 п.п.».
p10: с +3% тоже лок +0.5% net; бумажный трейл 10%→2% цены плюс лок пик − 10 с пика ≥ 10%.
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


def long_roe_pct(entry: float, price: float, leverage: int | None = None) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    if entry <= 0:
        return 0.0
    return (price - entry) / entry * lev * 100.0


def long_liquidation_price(entry: float, leverage: int | None = None, mmr: float | None = None) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    rate = config.PAPER_MAINT_MARGIN_RATE if mmr is None else mmr
    return entry * (1.0 - 1.0 / lev + rate)


def price_for_long_roe(entry: float, roe: float, leverage: int | None = None) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    return entry * (1.0 + roe / (100.0 * lev))


def net_breakeven_stop_price_long(
    entry: float,
    margin: float,
    leverage: int | None = None,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    if entry <= 0 or margin <= 0:
        return entry
    qty = margin * lev / entry
    fee = config.PAPER_FEE_RATE_TAKER
    return (entry * qty + entry_fee - funding_paid) / (qty * (1.0 - fee))


def net_roe_stop_price_long(
    entry: float,
    margin: float,
    roe_pct: float,
    leverage: int | None = None,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    if entry <= 0 or margin <= 0:
        return entry
    qty = margin * lev / entry
    fee = config.PAPER_FEE_RATE_TAKER
    target_pnl = margin * roe_pct / 100.0
    return (entry * qty + entry_fee - funding_paid + target_pnl) / (qty * (1.0 - fee))


def trail_stop_long(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    peak = long_roe_pct(entry, best_price, lev)
    if peak <= 0:
        return net_roe_stop_price_long(
            entry, margin, config.PAPER_LONG_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
        )
    if peak < config.PAPER_LONG_LOCK_ARM_ROE:
        if margin > 0:
            return net_breakeven_stop_price_long(entry, margin, lev, entry_fee, funding_paid)
        return price_for_long_roe(entry, 0.0, lev)
    lock_roe = max(config.PAPER_LONG_LOCK_MIN_ROE, peak - config.PAPER_LONG_TRAIL_GAP_ROE)
    return price_for_long_roe(entry, lock_roe, lev)


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


def price_for_roe(entry: float, roe: float, leverage: int | None = None) -> float:
    """Цена шорта, при которой gross ROE равен roe."""
    lev = leverage or config.PAPER_LEVERAGE
    return entry * (1.0 - roe / (100.0 * lev))


def net_roe_stop_price(
    entry: float,
    margin: float,
    roe_pct: float,
    leverage: int | None = None,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Цена выхода шорта с заданным net ROE (% от маржи)."""
    lev = leverage or config.PAPER_LEVERAGE
    if entry <= 0 or margin <= 0:
        return entry
    qty = margin * lev / entry
    fee = config.PAPER_FEE_RATE_TAKER
    target_pnl = margin * roe_pct / 100.0
    return (entry * qty - entry_fee + funding_paid - target_pnl) / (qty * (1.0 + fee))


def net_breakeven_stop_price(
    entry: float,
    margin: float,
    leverage: int | None = None,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Цена выхода шорта, при которой net P&L (комиссии + funding) ≈ 0."""
    lev = leverage or config.PAPER_LEVERAGE
    if entry <= 0 or margin <= 0:
        return entry
    qty = margin * lev / entry
    fee = config.PAPER_FEE_RATE_TAKER
    return (entry * qty - entry_fee + funding_paid) / (qty * (1.0 + fee))


def css_trail_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    """Cursor SS: стоп −15% ROE, с пика ≥ +10% ROE — net-безубыток, дальше трейл 20 п.п."""
    lev = leverage or config.PAPER_LEVERAGE
    peak = roe_pct(entry, best_price, lev)
    initial = net_roe_stop_price(
        entry, margin, config.PAPER_CSS_INITIAL_STOP_ROE, lev, entry_fee, funding_paid
    )
    if peak < config.PAPER_CSS_BE_ARM_ROE:
        return initial
    be = net_breakeven_stop_price(entry, margin, lev, entry_fee, funding_paid)
    lock_roe = peak - config.PAPER_CSS_TRAIL_GAP_ROE
    if lock_roe <= 0:
        return be
    return min(be, price_for_roe(entry, lock_roe, lev))


def sc10_trail_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
    side: str = "short",
) -> float:
    """Скальп 10: стоп всегда на 10 п.п. ROE позади пика (с входа это −10% ROE)."""
    lev = leverage or config.PAPER_LEVERAGE
    gap = config.PAPER_SC10_TRAIL_GAP_ROE
    if side == "long":
        peak = long_roe_pct(entry, best_price, lev)
        return net_roe_stop_price_long(
            entry, margin, peak - gap, lev, entry_fee, funding_paid
        )
    peak = roe_pct(entry, best_price, lev)
    return net_roe_stop_price(entry, margin, peak - gap, lev, entry_fee, funding_paid)


def trail_stop(
    entry: float,
    best_price: float,
    leverage: int | None = None,
    peak_gap_roe: float = 0.0,
    *,
    margin: float = 0.0,
    entry_fee: float = 0.0,
    funding_paid: float = 0.0,
) -> float:
    lev = leverage or config.PAPER_LEVERAGE
    peak = roe_pct(entry, best_price, lev)
    if peak >= config.PAPER_BE_ARM_ROE:
        if margin > 0:
            early = net_roe_stop_price(
                entry, margin, config.PAPER_BE_LOCK_NET_ROE, lev, entry_fee, funding_paid
            )
        else:
            early = price_for_roe(entry, config.PAPER_BE_LOCK_NET_ROE, lev)
    else:
        early = None
    if peak_gap_roe > 0:
        paper = best_price * (1.0 + trail_distance_pct(peak) / 100.0)
        stop = paper
        if early is not None:
            stop = min(stop, early)
        if peak >= peak_gap_roe:
            stop = min(stop, price_for_roe(entry, peak - peak_gap_roe, lev))
        return stop
    if peak < config.PAPER_BE_ARM_ROE:
        return liquidation_price(entry, lev)
    if peak < config.PAPER_LOCK_ARM_ROE:
        return early if early is not None else price_for_roe(entry, config.PAPER_BE_LOCK_NET_ROE, lev)
    lock_roe = max(config.PAPER_LOCK_MIN_ROE, peak - config.PAPER_TRAIL_GAP_ROE)
    return price_for_roe(entry, lock_roe, lev)


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
    peak_gap_roe: float = 0.0
    loss_cap_armed: bool = False
    side: str = "short"
    stop_style: str = "default"

    def __post_init__(self) -> None:
        if self.best_price <= 0:
            self.best_price = self.entry_price
        if self.worst_price <= 0:
            self.worst_price = self.entry_price
        if self.liq_price <= 0:
            self.liq_price = (
                long_liquidation_price(self.entry_price, self.leverage)
                if self.side == "long"
                else liquidation_price(self.entry_price, self.leverage)
            )
        if self.entry_fee <= 0:
            self.entry_fee = self.notional * config.PAPER_FEE_RATE_TAKER
        if self.stop_price <= 0:
            self._sync_stop(self.last_price if self.last_price > 0 else self.entry_price)
        if self.last_price <= 0:
            self.last_price = self.entry_price

    def _sync_stop(self, last: float) -> None:
        if self.stop_style == "css":
            trail = css_trail_stop(
                self.entry_price,
                self.best_price,
                self.leverage,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
            )
            self.stop_price = min(self.liq_price, trail)
            return
        if self.stop_style == "sc10":
            trail = sc10_trail_stop(
                self.entry_price,
                self.best_price,
                self.leverage,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
                side=self.side,
            )
            if self.side == "long":
                self.stop_price = max(self.liq_price, trail)
            else:
                self.stop_price = min(self.liq_price, trail)
            return
        if self.side == "long":
            trail = trail_stop_long(
                self.entry_price,
                self.best_price,
                self.leverage,
                margin=self.margin,
                entry_fee=self.entry_fee,
                funding_paid=self.funding_paid,
            )
            self.stop_price = max(self.liq_price, trail)
            return
        trail = trail_stop(
            self.entry_price,
            self.best_price,
            self.leverage,
            self.peak_gap_roe,
            margin=self.margin,
            entry_fee=self.entry_fee,
            funding_paid=self.funding_paid,
        )
        stop = min(self.liq_price, trail)
        if self.loss_cap_armed or self.gross_pnl(last) < 0:
            self.loss_cap_armed = True
            cap = net_roe_stop_price(
                self.entry_price,
                self.margin,
                config.PAPER_LOSS_CAP_ROE,
                self.leverage,
                self.entry_fee,
                self.funding_paid,
            )
            stop = min(stop, cap)
        self.stop_price = stop

    @property
    def notional(self) -> float:
        return self.margin * self.leverage

    @property
    def qty(self) -> float:
        return self.notional / self.entry_price

    def gross_pnl(self, price: float) -> float:
        if self.side == "long":
            return (price - self.entry_price) * self.qty
        return (self.entry_price - price) * self.qty

    def exit_fee(self, price: float) -> float:
        return self.qty * price * config.PAPER_FEE_RATE_TAKER

    def net_pnl(self, price: float) -> float:
        return self.gross_pnl(price) - self.entry_fee - self.exit_fee(price) + self.funding_paid

    def net_roe(self, price: float) -> float:
        return self.net_pnl(price) / self.margin * 100.0 if self.margin > 0 else 0.0

    def max_roe(self) -> float:
        if self.side == "long":
            return long_roe_pct(self.entry_price, self.best_price, self.leverage)
        return roe_pct(self.entry_price, self.best_price, self.leverage)

    def min_roe(self) -> float:
        if self.side == "long":
            return long_roe_pct(self.entry_price, self.worst_price, self.leverage)
        return roe_pct(self.entry_price, self.worst_price, self.leverage)

    def apply_funding(self, now_ms: int, rate: float | None, price: float) -> float:
        """Funding: шорт получает при rate>0, лонг платит."""
        if self.next_funding_ts is None or rate is None or now_ms < self.next_funding_ts:
            return 0.0
        payment = self.qty * price * rate
        if self.side == "long":
            payment = -payment
        self.funding_paid += payment
        self.next_funding_ts = None
        return payment

    def update(self, low: float, high: float, last: float) -> str | None:
        """Обновить по диапазону цен с прошлой проверки. Вернуть причину выхода."""
        self.last_price = last
        if self.side == "long":
            if low <= self.liq_price:
                self.worst_price = min(self.worst_price, self.liq_price)
                return "liquidation"
            if low <= self.stop_price:
                self.worst_price = min(self.worst_price, max(low, self.stop_price))
                return "trailing_stop"
            self.worst_price = min(self.worst_price, low)
            best_changed = high > self.best_price
            if best_changed:
                self.best_price = high
            prev_stop = self.stop_price
            self._sync_stop(last)
            if self.stop_price > prev_stop + 1e-12 and last <= self.stop_price:
                return "trailing_stop"
            return None
        if high >= self.liq_price:
            self.worst_price = max(self.worst_price, self.liq_price)
            return "liquidation"
        if high >= self.stop_price:
            self.worst_price = max(self.worst_price, min(high, self.stop_price))
            return "trailing_stop"
        self.worst_price = max(self.worst_price, high)
        best_changed = low < self.best_price
        if best_changed:
            self.best_price = low
        prev_stop = self.stop_price
        self._sync_stop(last)
        if self.stop_price < prev_stop - 1e-12 and last >= self.stop_price:
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
