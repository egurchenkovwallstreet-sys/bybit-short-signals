"""Вкладка EMA6 Bybit: снимок из Redis или SQLite."""

from __future__ import annotations

from typing import Any

from signal_engine.live.em6_bybit.board import merge_public_snapshot, snapshot_from_db_fallback


class Em6BybitCache:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    def apply(self, envelope: dict[str, Any]) -> bool:
        if envelope.get("type") != "em6_bybit":
            return False
        data = envelope.get("data")
        if isinstance(data, dict):
            self.payload = data
        return True

    def view(self) -> dict[str, Any] | None:
        return self.payload


def snapshot_from_db() -> dict[str, Any]:
    return snapshot_from_db_fallback()


def snapshot_for_ui(engine_cache: dict[str, Any] | None) -> dict[str, Any]:
    return merge_public_snapshot(engine_cache)
