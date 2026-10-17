"""Сторона бумажной сделки: колонка, entry_json, kind, вариант."""

from __future__ import annotations

from typing import Any

import config
from signal_engine.paper.position import liquidation_price, long_liquidation_price


def resolve_trade_side(
    *,
    side: str | None = None,
    kind: str = "",
    variant: str = "",
    entry: dict | None = None,
) -> str:
    raw = str(side or "").strip().lower()
    if raw in ("long", "short"):
        return raw
    blob = entry if isinstance(entry, dict) else {}
    metrics = blob.get("metrics") if isinstance(blob.get("metrics"), dict) else {}
    pump = metrics.get("pump") if isinstance(metrics.get("pump"), dict) else {}
    for candidate in (blob.get("side"), metrics.get("side"), pump.get("side")):
        value = str(candidate or "").strip().lower()
        if value in ("long", "short"):
            return value
    kind_s = str(kind or "")
    if kind_s.endswith("_long"):
        return "long"
    if kind_s.endswith("_short"):
        return "short"
    if variant and config.paper_is_long(str(variant)):
        return "long"
    return "short"


def liq_price_for_side(side: str, entry_price: float, leverage: int | None = None) -> float:
    if side == "long":
        return long_liquidation_price(entry_price, leverage)
    return liquidation_price(entry_price, leverage)


def entry_from_raw(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            import json

            value = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}
    return {}
