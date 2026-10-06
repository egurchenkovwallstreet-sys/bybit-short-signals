"""Отбор USDT-перпетуалов: без innovation/delisting, возраст и объём."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import config
from collector.instruments import is_tracked_contract


# Статусы и типы, которые не берём в мониторинг.
_NON_TRADING_STATUSES = frozenset(
    {
        "Closed",
        "Delivering",
        "Settling",
        "PreLaunch",
        "PendingOpen",
    }
)
_EXCLUDED_SYMBOL_TYPES = frozenset({"innovation"})


@dataclass
class UniverseFilterStats:
    raw: int = 0
    kept: int = 0
    skipped_not_perp: int = 0
    skipped_status: int = 0
    skipped_pre_listing: int = 0
    skipped_innovation: int = 0
    skipped_delisting: int = 0
    skipped_too_young: int = 0
    skipped_no_launch: int = 0
    skipped_no_ticker: int = 0
    skipped_low_volume: int = 0

    def bump(self, reason: str) -> None:
        mapping = {
            "not_perp": "skipped_not_perp",
            "status": "skipped_status",
            "pre_listing": "skipped_pre_listing",
            "innovation": "skipped_innovation",
            "delisting": "skipped_delisting",
            "too_young": "skipped_too_young",
            "no_launch": "skipped_no_launch",
            "no_ticker": "skipped_no_ticker",
            "low_volume": "skipped_low_volume",
        }
        attr = mapping.get(reason)
        if attr:
            setattr(self, attr, getattr(self, attr) + 1)


def _is_innovation_zone(item: dict[str, Any]) -> bool:
    sym_type = str(item.get("symbolType") or "").strip().lower()
    if sym_type in _EXCLUDED_SYMBOL_TYPES:
        return True
    legacy = item.get("innovation")
    if legacy not in (None, "", "0", 0, False):
        return True
    group = str(item.get("groupName") or "")
    if "Innovation" in group or "innovation" in group.lower():
        return True
    group_id = item.get("groupId")
    if str(group_id) == "6":
        return True
    return False


def _scheduled_delisting(item: dict[str, Any]) -> bool:
    """У перпетуала deliveryTime > 0 — запланированный delist."""
    try:
        delivery_ms = int(item.get("deliveryTime") or 0)
    except (TypeError, ValueError):
        return False
    return delivery_ms > 0


def reject_reason(
    item: dict[str, Any],
    turnover_24h: float | None,
    *,
    now_ms: int,
    min_turnover_usdt: float,
    min_listing_age_ms: int,
) -> str | None:
    if not is_tracked_contract(item):
        return "not_perp"
    status = str(item.get("status") or "")
    if status != "Trading" or status in _NON_TRADING_STATUSES:
        return "status"
    if item.get("isPreListing"):
        return "pre_listing"
    if _is_innovation_zone(item):
        return "innovation"
    if _scheduled_delisting(item):
        return "delisting"
    try:
        launch_ms = int(item.get("launchTime") or 0)
    except (TypeError, ValueError):
        launch_ms = 0
    if launch_ms <= 0:
        return "no_launch"
    if now_ms - launch_ms < min_listing_age_ms:
        return "too_young"
    if turnover_24h is None:
        return "no_ticker"
    if turnover_24h < min_turnover_usdt:
        return "low_volume"
    return None


def filter_universe(
    instruments: list[dict[str, Any]],
    turnover_by_symbol: dict[str, float],
    *,
    now_ms: int,
    min_turnover_usdt: float | None = None,
    min_listing_age_ms: int | None = None,
) -> tuple[list[str], UniverseFilterStats]:
    min_turnover_usdt = (
        float(min_turnover_usdt)
        if min_turnover_usdt is not None
        else float(config.UNIVERSE_MIN_TURNOVER_24H_USDT)
    )
    min_listing_age_ms = (
        int(min_listing_age_ms)
        if min_listing_age_ms is not None
        else int(config.UNIVERSE_MIN_LISTING_AGE_DAYS) * 86400 * 1000
    )
    stats = UniverseFilterStats(raw=len(instruments))
    kept: list[str] = []
    for item in instruments:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not symbol:
            continue
        turnover = turnover_by_symbol.get(str(symbol))
        reason = reject_reason(
            item,
            turnover,
            now_ms=now_ms,
            min_turnover_usdt=min_turnover_usdt,
            min_listing_age_ms=min_listing_age_ms,
        )
        if reason:
            stats.bump(reason)
            continue
        kept.append(str(symbol))
    stats.kept = len(kept)
    return sorted(set(kept)), stats
