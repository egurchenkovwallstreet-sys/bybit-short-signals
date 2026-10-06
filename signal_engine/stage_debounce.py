"""Подтверждение смены стадии/колонки по горизонту времени."""

from __future__ import annotations

import config


def resolve_stage(
    *,
    confirmed: int,
    candidate: int,
    pending_stage: int | None,
    pending_since: int | None,
    now_ms: int,
    allow_down: bool = True,
    continued_pump: bool = False,
) -> tuple[int, int | None, int | None]:
    """Возвращает (новая confirmed, pending_stage, pending_since)."""
    if candidate == confirmed:
        return confirmed, None, None
    if candidate > confirmed:
        need = config.WATCH_STAGE_CONFIRM_MS
    elif not allow_down:
        return confirmed, None, None
    elif continued_pump:
        need = config.WATCH_STAGE_CONFIRM_MS
    else:
        need = config.WATCH_STAGE_DOWN_CONFIRM_MS

    if pending_stage != candidate or pending_since is None:
        return confirmed, candidate, now_ms
    if now_ms - pending_since >= need:
        return candidate, None, None
    return confirmed, pending_stage, pending_since
