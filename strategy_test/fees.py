"""Комиссия Bybit USDT-perp (taker) в расчёте PnL тестовой стратегии."""

from __future__ import annotations

import config


def round_trip_fee_pct() -> float:
    """Суммарный % от номинала за открытие + закрытие (обе стороны taker)."""
    return 2.0 * config.BTC_TEST_FEE_RATE_TAKER * 100.0


def net_pnl_pct(gross_pnl_pct: float) -> float:
    """Gross PnL уже с плечом; вычитаем комиссию, масштабированную плечом."""
    drag = round_trip_fee_pct() * config.PNL_LEVERAGE
    return gross_pnl_pct - drag
