"""Цифры для вкладки «Статистика» — бумажные стратегии (paper_strategy.db)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import config
from signal_engine.paper.stats_dashboard import compute_paper_stats_dashboard, empty_paper_stats_dashboard


def empty_stats() -> dict[str, Any]:
    return empty_paper_stats_dashboard()


def compute_stats(path: Path | str | None = None) -> dict[str, Any]:
    database = Path(path or config.PAPER_SQLITE_PATH)
    return compute_paper_stats_dashboard(database)
