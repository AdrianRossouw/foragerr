"""Typed command models and handler registry (FRG-SCHED-001/003).

Commands are Pydantic models discriminated on their ``name`` field; the
payload is everything except ``name``. Enqueue-time validation goes through
:func:`parse_command` — an unknown name or invalid payload raises
:class:`CommandValidationError` and never touches the database.

De-duplication (FRG-SCHED-003) keys on ``(name, payload_hash)`` where the
hash is a SHA-256 of the canonical (sorted, compact) JSON payload.
"""

from __future__ import annotations

import hashlib
import json
from typing import (
    Annotated,
    Any,
    Awaitable,
    Callable,
    ClassVar,
    Literal,
    Union,
)

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

__all__ = [
    "BaseCommand",
    "CommandValidationError",
    "HousekeepingCommand",
    "NoOpCommand",
    "command_names",
    "get_handler",
    "parse_command",
    "payload_hash",
    "payload_json",
    "register_command",
    "register_handler",
    "restore_registry",
    "snapshot_registry",
]


class CommandValidationError(ValueError):
    """Unknown command name or payload that fails validation (FRG-SCHED-001)."""


class BaseCommand(BaseModel):
    """Base for all commands; subclasses set ``name`` to a unique Literal.

    Class-level metadata drives queueing behavior:
    - ``workload_class``: which worker pool runs it (FRG-SCHED-005)
    - ``default_priority``: higher runs first (FRG-SCHED-004)
    - ``exclusivity_group``: at most one command of the group runs at a time
    """

    model_config = ConfigDict(extra="forbid")

    workload_class: ClassVar[str] = "default"
    default_priority: ClassVar[int] = 0
    exclusivity_group: ClassVar[str | None] = None

    name: str


_COMMAND_TYPES: dict[str, type[BaseCommand]] = {}
_HANDLERS: dict[str, "Handler"] = {}
_adapter_cache: TypeAdapter[Any] | None = None

Handler = Callable[[BaseCommand, Any], Awaitable[str | None]]


def register_command(cls: type[BaseCommand]) -> type[BaseCommand]:
    """Class decorator adding a command model to the discriminated union."""
    global _adapter_cache
    name = cls.model_fields["name"].default
    if not isinstance(name, str) or not name:
        raise TypeError(
            f"{cls.__name__} must declare `name: Literal[\"<name>\"] = \"<name>\"`"
        )
    _COMMAND_TYPES[name] = cls
    _adapter_cache = None
    return cls


def register_handler(name: str) -> Callable[[Handler], Handler]:
    """Decorator registering the async handler for a command name."""

    def decorate(handler: Handler) -> Handler:
        _HANDLERS[name] = handler
        return handler

    return decorate


def get_handler(name: str) -> Handler:
    handler = _HANDLERS.get(name)
    if handler is None:
        raise KeyError(f"no handler registered for command {name!r}")
    return handler


def command_names() -> list[str]:
    return sorted(_COMMAND_TYPES)


def command_type(name: str) -> type[BaseCommand] | None:
    return _COMMAND_TYPES.get(name)


def _adapter() -> TypeAdapter[Any]:
    """TypeAdapter over the discriminated union of all registered commands."""
    global _adapter_cache
    if _adapter_cache is None:
        types = tuple(_COMMAND_TYPES.values())
        if not types:
            raise RuntimeError("no command types registered")
        if len(types) == 1:
            _adapter_cache = TypeAdapter(types[0])
        else:
            _adapter_cache = TypeAdapter(
                Annotated[Union[types], Field(discriminator="name")]
            )
    return _adapter_cache


def parse_command(name: str, payload: dict[str, Any] | None = None) -> BaseCommand:
    """Validate ``(name, payload)`` into a typed command instance.

    Raises :class:`CommandValidationError` for unknown names or invalid
    payloads — callers must not create any DB row in that case.
    """
    if name not in _COMMAND_TYPES:
        raise CommandValidationError(
            f"unknown command name {name!r}; known commands: {command_names()}"
        )
    data = dict(payload or {})
    data["name"] = name
    try:
        return _adapter().validate_python(data)
    except ValidationError as exc:
        raise CommandValidationError(
            f"invalid payload for command {name!r}: {exc}"
        ) from exc


def payload_json(command: BaseCommand) -> str:
    """Canonical JSON of the payload (everything but ``name``)."""
    return json.dumps(
        command.model_dump(mode="json", exclude={"name"}),
        sort_keys=True,
        separators=(",", ":"),
    )


def payload_hash(command: BaseCommand) -> str:
    """Dedup key over the canonical payload (FRG-SCHED-003)."""
    return hashlib.sha256(payload_json(command).encode("utf-8")).hexdigest()


def snapshot_registry() -> tuple[dict[str, type[BaseCommand]], dict[str, Handler]]:
    """Copy of the registries (test isolation helper)."""
    return dict(_COMMAND_TYPES), dict(_HANDLERS)


def restore_registry(
    snapshot: tuple[dict[str, type[BaseCommand]], dict[str, Handler]],
) -> None:
    """Restore a snapshot taken by :func:`snapshot_registry`."""
    global _adapter_cache
    types, handlers = snapshot
    _COMMAND_TYPES.clear()
    _COMMAND_TYPES.update(types)
    _HANDLERS.clear()
    _HANDLERS.update(handlers)
    _adapter_cache = None


# --- built-in commands -----------------------------------------------------


@register_command
class NoOpCommand(BaseCommand):
    """Trivial test command so the api area can exercise POST /command."""

    name: Literal["noop"] = "noop"
    note: str | None = None


@register_command
class HousekeepingCommand(BaseCommand):
    """Retention pruning of job_history and other periodic tidy-up
    (FRG-SCHED-008)."""

    name: Literal["housekeeping"] = "housekeeping"
    exclusivity_group: ClassVar[str | None] = "housekeeping"
