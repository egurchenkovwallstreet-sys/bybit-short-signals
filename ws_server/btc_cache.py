"""Кэш тестовой BTC-стратегии для WebSocket."""

from __future__ import annotations

from typing import Any


class BtcTestCache:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None
        self.dirty = False

    def apply(self, envelope: dict[str, Any]) -> bool:
        if envelope.get("type") != "btc_strategy":
            return False
        data = envelope.get("data")
        if isinstance(data, dict):
            self.payload = data
            self.dirty = True
        return True

    def view(self) -> dict[str, Any] | None:
        return self.payload
