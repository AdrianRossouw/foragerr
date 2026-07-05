"""The download-client implementation registry (FRG-DL-001/002).

Mirrors :mod:`foragerr.indexers.registry`: maps an implementation identifier
(``sabnzbd`` / ``ddl``) to its settings contract, presentation metadata, wire
protocol, and a client factory. This is the extensibility seam — a new client is
a registry entry plus a settings model, no frontend change and no new endpoint.

The ``ddl`` implementation is registered here (protocol ``ddl``) so DDL is "just
another client" from day one, but its concrete client factory is supplied by the
ddl worktree area via :func:`set_client_factory` at that package's import time —
the foundation area does not depend on the ddl client code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Type

from pydantic import BaseModel, ValidationError

from foragerr.downloads.settings import BuiltinDdlSettings, SabnzbdSettings

if TYPE_CHECKING:  # typing only — avoids importing httpx/db at module import
    from pydantic import BaseModel as _SettingsModel

    from foragerr.config import Settings
    from foragerr.db.engine import Database
    from foragerr.downloads.clients.base import DownloadClient
    from foragerr.downloads.models import DownloadClientRow
    from foragerr.downloads.pathmap import RemotePathMapping
    from foragerr.http import HttpClientFactory
    from foragerr.providers.backoff import ProviderBackoff

#: Wire protocols matched at grab dispatch (FRG-DL-002). Usenet → SABnzbd,
#: ddl → the built-in DDL client. The protocol a release routes to is DERIVED
#: from the release's indexer row's ``protocol`` column, not carried on the grab.
PROTOCOL_USENET = "usenet"
PROTOCOL_DDL = "ddl"


@dataclass(frozen=True, slots=True)
class ClientBuildContext:
    """Everything a client factory needs to build a live :class:`DownloadClient`.

    Assembled by :func:`foragerr.downloads.resolver.resolve_client_for` (and by
    the schema/test endpoint), so a factory stays a pure ``ctx -> client`` map.
    """

    row: "DownloadClientRow"
    settings: "_SettingsModel"
    db: "Database"
    http_factory: "HttpClientFactory"
    backoff: "ProviderBackoff"
    mappings: list["RemotePathMapping"]
    app_settings: "Settings | None" = None


ClientFactory = Callable[[ClientBuildContext], "DownloadClient"]


@dataclass(slots=True)
class Implementation:
    """One registered download-client implementation.

    ``client_factory`` is mutable so the ddl area can supply its concrete factory
    after import without editing this registry (:func:`set_client_factory`).
    """

    name: str  # stable identifier persisted on the row (``implementation``)
    label: str  # human-facing name for the schema listing
    protocol: str
    settings_model: Type[BaseModel]
    client_factory: ClientFactory | None = None


def _build_sabnzbd(ctx: ClientBuildContext) -> "DownloadClient":
    """Factory for the ``sabnzbd`` implementation (imported lazily to avoid a
    module-level dependency on httpx from the registry)."""
    from foragerr.downloads.clients.sabnzbd import SabnzbdClient

    return SabnzbdClient.from_context(ctx)


#: The registry. Newznab-style static seed; ``ddl`` starts factory-less until
#: the ddl area registers its client (FRG-DDL-001).
_IMPLEMENTATIONS: dict[str, Implementation] = {
    "sabnzbd": Implementation(
        name="sabnzbd",
        label="SABnzbd",
        protocol=PROTOCOL_USENET,
        settings_model=SabnzbdSettings,
        client_factory=_build_sabnzbd,
    ),
    "ddl": Implementation(
        name="ddl",
        label="GetComics (built-in DDL)",
        protocol=PROTOCOL_DDL,
        settings_model=BuiltinDdlSettings,
        client_factory=None,  # supplied by the ddl area via set_client_factory
    ),
}


class UnknownImplementationError(ValueError):
    """The requested download-client implementation is not registered."""


def implementations() -> list[Implementation]:
    """Every registered implementation, in a stable declared order."""
    return list(_IMPLEMENTATIONS.values())


def get_implementation(name: str) -> Implementation:
    """Look up one implementation or raise :class:`UnknownImplementationError`."""
    try:
        return _IMPLEMENTATIONS[name]
    except KeyError:
        raise UnknownImplementationError(
            f"unknown download-client implementation {name!r}; "
            f"known: {', '.join(sorted(_IMPLEMENTATIONS))}"
        ) from None


def implementations_for_protocol(protocol: str) -> list[Implementation]:
    """Every registered implementation whose wire protocol matches (FRG-DL-002)."""
    return [impl for impl in _IMPLEMENTATIONS.values() if impl.protocol == protocol]


def set_client_factory(name: str, factory: ClientFactory) -> None:
    """Attach a concrete client factory to an implementation (ddl-area hook).

    Lets the ddl worktree area wire its GetComics client into the ``ddl``
    implementation at import time without editing this foundation module.
    """
    get_implementation(name).client_factory = factory


def validate_settings(name: str, payload: dict) -> BaseModel:
    """Validate a raw settings payload against its implementation's contract.

    Returns the parsed settings model or raises ``ValidationError`` (field
    level) / :class:`UnknownImplementationError`. No row is persisted here.
    """
    impl = get_implementation(name)
    return impl.settings_model.model_validate(payload)


__all__ = [
    "PROTOCOL_DDL",
    "PROTOCOL_USENET",
    "ClientBuildContext",
    "ClientFactory",
    "Implementation",
    "UnknownImplementationError",
    "ValidationError",
    "get_implementation",
    "implementations",
    "implementations_for_protocol",
    "set_client_factory",
    "validate_settings",
]
