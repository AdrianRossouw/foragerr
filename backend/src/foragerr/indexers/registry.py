"""The indexer implementation registry (FRG-IDX-001, FRG-IDX-003).

Maps an implementation identifier (``newznab``) to its settings contract and
presentation metadata. This is the extensibility seam (design decision 1):
adding a future implementation (Torznab in M2, say) is a registry entry plus a
settings model — no frontend change, no new endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel, ValidationError

from foragerr.indexers.settings import NewznabSettings

#: Wire protocol for an implementation — usenet indexers are Newznab today;
#: Torznab (torrents) arrives in M2 as a second registry row (FRG-IDX-012).
PROTOCOL_USENET = "usenet"


@dataclass(frozen=True, slots=True)
class Implementation:
    """One registered indexer implementation."""

    name: str  # stable identifier, persisted on the row (``implementation``)
    label: str  # human-facing name for the schema listing
    protocol: str
    settings_model: Type[BaseModel]


#: The M1 registry. Newznab is the only implementation; the pattern is the
#: point (FRG-IDX-001 notes: meta-indexers are plain Newznab rows).
_IMPLEMENTATIONS: dict[str, Implementation] = {
    "newznab": Implementation(
        name="newznab",
        label="Newznab",
        protocol=PROTOCOL_USENET,
        settings_model=NewznabSettings,
    ),
}


class UnknownImplementationError(ValueError):
    """The requested implementation identifier is not registered."""


def implementations() -> list[Implementation]:
    """Every registered implementation, in a stable declared order."""
    return list(_IMPLEMENTATIONS.values())


def get_implementation(name: str) -> Implementation:
    """Look up one implementation or raise :class:`UnknownImplementationError`."""
    try:
        return _IMPLEMENTATIONS[name]
    except KeyError:
        raise UnknownImplementationError(
            f"unknown indexer implementation {name!r}; "
            f"known: {', '.join(sorted(_IMPLEMENTATIONS))}"
        ) from None


def validate_settings(name: str, payload: dict) -> BaseModel:
    """Validate a raw settings payload against its implementation's contract.

    Returns the parsed settings model, or raises ``ValidationError`` (field
    level) / :class:`UnknownImplementationError`. No row is persisted here —
    persistence is the caller's job, only after this returns cleanly
    (FRG-IDX-001 "no partial row is persisted").
    """
    impl = get_implementation(name)
    return impl.settings_model.model_validate(payload)


__all__ = [
    "Implementation",
    "PROTOCOL_USENET",
    "UnknownImplementationError",
    "ValidationError",
    "get_implementation",
    "implementations",
    "validate_settings",
]
