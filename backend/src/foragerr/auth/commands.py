"""Scheduled session pruning (FRG-AUTH-004).

Importing this module registers the ``prune-sessions`` command + handler;
:func:`register_prune_sessions_task` wires the recurring task onto the existing
scheduler. Mirrors the ``prune-release-cache`` housekeeping pattern.
"""

from __future__ import annotations

import logging
from typing import ClassVar, Literal

from foragerr.auth import sessions as sessions_mod
from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext

logger = logging.getLogger("foragerr.auth")

PRUNE_SESSIONS_TASK = "prune-sessions"
#: Hourly is ample: sliding expiry already bounds live rows; this only reclaims
#: rows past expiry. Floored so an operator cannot set an abusive cadence.
PRUNE_SESSIONS_INTERVAL = 3600
PRUNE_SESSIONS_MIN_INTERVAL = 300


@register_command
class PruneSessionsCommand(BaseCommand):
    """Scheduled prune of expired session rows (FRG-AUTH-004)."""

    name: Literal["prune-sessions"] = "prune-sessions"
    exclusivity_group: ClassVar[str | None] = "prune-sessions"


@register_handler("prune-sessions")
async def _handle_prune_sessions(
    command: PruneSessionsCommand, ctx: HandlerContext
) -> str:
    pruned = await sessions_mod.prune_expired(ctx.db)
    return f"pruned {pruned} expired session row(s)"


async def register_prune_sessions_task(scheduler, settings) -> None:
    await scheduler.register_task(
        PRUNE_SESSIONS_TASK,
        PRUNE_SESSIONS_TASK,
        interval_seconds=PRUNE_SESSIONS_INTERVAL,
        min_interval_seconds=PRUNE_SESSIONS_MIN_INTERVAL,
    )


__all__ = [
    "PRUNE_SESSIONS_TASK",
    "PruneSessionsCommand",
    "register_prune_sessions_task",
]
