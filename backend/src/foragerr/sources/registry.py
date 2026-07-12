"""The store-source type registry (FRG-SRC-001).

Maps a store-type identifier (``humble``) to its settings contract and
presentation metadata — the same zero-frontend extensibility seam the indexer
registry provides. Humble is the only connectable type in this change; a second
store (2000 AD, archive.org) is a registry entry plus a settings model, no new
endpoint (proposal Non-goals: the model is generic, one implementation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel

from foragerr.sources.settings import HumbleSettings

#: The Humble store-type identifier, persisted on ``sources.type``.
TYPE_HUMBLE = "humble"


@dataclass(frozen=True, slots=True)
class SourceType:
    """One registered store-source type."""

    name: str  # stable identifier, persisted on the row (``type``)
    label: str  # human-facing name for the schema listing
    settings_model: Type[BaseModel]


_SOURCE_TYPES: dict[str, SourceType] = {
    TYPE_HUMBLE: SourceType(
        name=TYPE_HUMBLE,
        label="Humble Bundle",
        settings_model=HumbleSettings,
    ),
}


class UnknownSourceTypeError(ValueError):
    """The requested store-type identifier is not registered."""


def implementations() -> list[SourceType]:
    """Every registered store type, in a stable declared order."""
    return list(_SOURCE_TYPES.values())


def get_source_type(name: str) -> SourceType:
    """Look up one store type or raise :class:`UnknownSourceTypeError`."""
    try:
        return _SOURCE_TYPES[name]
    except KeyError:
        raise UnknownSourceTypeError(
            f"unknown source type {name!r}; known: {', '.join(sorted(_SOURCE_TYPES))}"
        ) from None


def validate_settings(name: str, payload: dict) -> BaseModel:
    """Validate a raw settings payload against its store type's contract.

    Returns the parsed settings model, or raises ``ValidationError`` (field
    level) / :class:`UnknownSourceTypeError`. No row is persisted here.
    """
    source_type = get_source_type(name)
    return source_type.settings_model.model_validate(payload)


__all__ = [
    "SourceType",
    "TYPE_HUMBLE",
    "UnknownSourceTypeError",
    "get_source_type",
    "implementations",
    "validate_settings",
]
