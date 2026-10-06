"""Снимок BTC-теста из SQLite, если Redis ещё не прислал данные."""

from __future__ import annotations

from typing import Any

import config
from strategy_test.analytics import compute_analytics
from strategy_test.markers import markers_from_signals
from strategy_test.store import BtcStrategyStore


def btc_snapshot_from_db() -> dict[str, Any] | None:
    path = config.BTC_TEST_SQLITE_PATH
    if not path.exists():
        return None
    store = BtcStrategyStore(path)
    store.open()
    try:
        rows = store.list_signals(150)
    finally:
        store.close()
    if not rows:
        return None
    analytics = compute_analytics(rows)
    return {
        "symbol": config.BTC_TEST_SYMBOL,
        "bias": None,
        "last_price": None,
        "funding": None,
        "candles": [],
        "candles_by_tf": {},
        "markers": markers_from_signals(rows),
        "signals": rows,
        "analytics": analytics,
        "open": {},
        "hydrated_from_db": True,
    }
