"""Чтение лаборатории пампа из SQLite для REST."""

from __future__ import annotations

import json
from typing import Any

import config
from signal_engine.pump_lab.metrics import METRIC_GROUPS, METRIC_LABELS
from signal_engine.pump_lab.store import PumpLabStore


def _store() -> PumpLabStore:
    s = PumpLabStore(config.PUMP_LAB_SQLITE_PATH)
    s.open()
    return s


def episode_detail(episode_id: int) -> dict[str, Any] | None:
    store = _store()
    try:
        ep = store.episode(episode_id)
        if ep is None:
            return None
        history: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for metric_id in METRIC_LABELS:
            history[metric_id] = {}
            for horizon in ("short", "mid", "long"):
                history[metric_id][horizon] = store.metric_history(episode_id, metric_id, horizon)
        return {
            "episode": ep,
            "snapshots": store.recent_snapshots(episode_id, 30),
            "history": history,
            "metric_labels": METRIC_LABELS,
            "metric_groups": [{"id": g[0], "title": g[1]} for g in METRIC_GROUPS],
        }
    finally:
        store.close()


def board_from_db() -> dict[str, Any]:
    from signal_engine.pump_lab.lab import PumpLab

    lab = PumpLab()
    lab.open()
    try:
        return lab.build_board(int(__import__("time").time() * 1000))
    finally:
        lab.close()
