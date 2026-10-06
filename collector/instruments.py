"""Разбор ответа instruments-info Bybit."""

from __future__ import annotations

from typing import Any

import config


def is_tracked_contract(item: dict[str, Any]) -> bool:
    """USDT-перпетуал в статусе Trading. Срочные фьючерсы и другие котировки — мимо."""
    return (
        item.get("quoteCoin") == config.BYBIT_QUOTE
        and item.get("contractType") == "LinearPerpetual"
        and item.get("status") == "Trading"
    )


def symbols_from_instruments(payload: dict[str, Any]) -> tuple[list[str], str]:
    """Достать символы и курсор следующей страницы из ответа instruments-info."""
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("В ответе Bybit нет result")
    symbols = [
        item["symbol"]
        for item in result.get("list") or []
        if isinstance(item, dict) and is_tracked_contract(item) and item.get("symbol")
    ]
    cursor = result.get("nextPageCursor") or ""
    return symbols, str(cursor)
