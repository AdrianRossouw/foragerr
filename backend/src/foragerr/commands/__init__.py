"""foragerr command backbone (FRG-SCHED-001..005): typed commands, persisted
queue, worker pools, and startup recovery."""

from __future__ import annotations

from foragerr.commands.registry import (
    BaseCommand,
    CommandValidationError,
    HousekeepingCommand,
    NoOpCommand,
    command_names,
    parse_command,
    payload_hash,
    payload_json,
    register_command,
    register_handler,
)
from foragerr.commands.service import (
    CommandRecord,
    CommandService,
    DEFAULT_POOL_SIZES,
    HandlerContext,
    prune_job_history,
)

__all__ = [
    "BaseCommand",
    "CommandRecord",
    "CommandService",
    "CommandValidationError",
    "DEFAULT_POOL_SIZES",
    "HandlerContext",
    "HousekeepingCommand",
    "NoOpCommand",
    "command_names",
    "parse_command",
    "payload_hash",
    "payload_json",
    "prune_job_history",
    "register_command",
    "register_handler",
]
