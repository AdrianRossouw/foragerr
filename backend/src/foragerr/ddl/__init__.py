"""The built-in DDL (GetComics) area (FRG-DDL-001..013).

Importing this package performs the three registrations that make DDL "just
another provider/client" without any core module depending on this area:

1. the DDL **download client** factory is attached to the ``ddl`` implementation
   the downloads (foundation) area pre-registered (``set_client_factory``), so a
   ``ddl``-protocol grab resolves to :class:`~foragerr.ddl.client.DdlClient`;
2. the GetComics **search provider** is registered both as an indexer
   *implementation* (``getcomics``, protocol ``ddl``) and as the search-provider
   the change-4 pipeline dispatches ``ddl`` rows to, so its results feed the ONE
   shared decision engine;
3. the **process-ddl-queue** command + handler register (via importing
   :mod:`foragerr.ddl.commands`) so the persistent queue engine runs on the
   ``download`` pool.

``foragerr.app`` triggers all of this with one ``import foragerr.ddl``.
"""

from __future__ import annotations

from foragerr.ddl.client import DdlClient
from foragerr.ddl.search_provider import search_getcomics
from foragerr.ddl.settings import GetComicsSettings
from foragerr.downloads.registry import PROTOCOL_DDL, set_client_factory
from foragerr.indexers.registry import Implementation, register_implementation
from foragerr.indexers.service import register_search_provider

#: The GetComics search-provider implementation id (an ``indexers`` row).
GETCOMICS_IMPLEMENTATION = "getcomics"


def _register() -> None:
    """Idempotent registration of the client factory + search provider."""
    set_client_factory("ddl", DdlClient.from_context)
    register_implementation(
        Implementation(
            name=GETCOMICS_IMPLEMENTATION,
            label="GetComics (DDL)",
            protocol=PROTOCOL_DDL,
            settings_model=GetComicsSettings,
        )
    )
    register_search_provider(GETCOMICS_IMPLEMENTATION, search_getcomics)


_register()

# Import for the command/handler decorator side effects (process-ddl-queue).
from foragerr.ddl import commands as _commands  # noqa: E402,F401

__all__ = ["GETCOMICS_IMPLEMENTATION"]
