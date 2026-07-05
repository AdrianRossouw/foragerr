"""Grab-dispatch client resolution (FRG-DL-002).

Selects the enabled download client a release routes to, by matching the
release's PROTOCOL to a configured client. The reality-check finding this area
pins for wave B: the protocol is **derived** from the release's ``indexer_id`` →
that indexer/provider row's ``protocol`` column (usenet → SABnzbd, ddl → the
built-in DDL client), it is NOT carried on ``GrabReleaseCommand`` /
``ReleaseCandidate``.

If no enabled client matches, or the matched client is unreachable at grab time,
the caller (the tracking area's live grab handler) gets a TYPED failure so the
release cache entry stays valid and the grab is retryable — never a silently
dropped grab (FRG-DL-002 scenario 3). This module only resolves + instantiates;
it never mutates the grab command or the release cache.
"""

from __future__ import annotations

import logging

from foragerr.downloads.clients.base import DownloadClient
from foragerr.downloads.errors import NoDownloadClientError
from foragerr.downloads.registry import ClientBuildContext, get_implementation
from foragerr.downloads.repo import load_download_clients, load_mappings, load_settings
from foragerr.indexers.models import IndexerRow
from foragerr.search_ops.grab import GrabReleaseCommand

logger = logging.getLogger("foragerr.downloads.resolver")


async def protocol_for_indexer(db, indexer_id: int) -> str:
    """The wire protocol a release from ``indexer_id`` routes to (FRG-DL-002).

    Derived from the indexer/provider row's ``protocol`` column — the same row
    the DDL provider is registered as (a change-4 search provider with protocol
    ``ddl``). Raises :class:`NoDownloadClientError` when the indexer row is gone
    (a typed, retryable failure, never a silent drop).
    """
    async with db.read_session() as session:
        row = await session.get(IndexerRow, indexer_id)
    if row is None:
        raise NoDownloadClientError(
            f"cannot resolve protocol: indexer {indexer_id} no longer exists"
        )
    return row.protocol


async def protocol_for_grab(db, request: GrabReleaseCommand) -> str:
    """The protocol for a grab, derived from its ``indexer_id`` (FRG-DL-002)."""
    return await protocol_for_indexer(db, request.indexer_id)


async def resolve_client_for(
    db,
    protocol: str,
    *,
    http_factory,
    backoff,
    app_settings=None,
) -> DownloadClient:
    """Instantiate the enabled client that serves ``protocol`` (FRG-DL-002).

    Selection: among enabled, loadable clients whose implementation's protocol
    matches, the one with the lowest ``priority`` value wins (ties broken by id)
    — the priority/round-robin shape kept so a second client is config, not code.

    Raises :class:`NoDownloadClientError` (typed, retryable) when no enabled
    client matches the protocol, or when the matched implementation has no client
    factory wired yet (e.g. the ddl client before the ddl area registers it).
    """
    listing = await load_download_clients(db)
    matching = [
        row
        for row in listing.healthy
        if row.enabled and get_implementation(row.implementation).protocol == protocol
    ]
    if not matching:
        raise NoDownloadClientError(
            f"no enabled download client for protocol {protocol!r}; "
            "configure one — the grab stays retryable"
        )
    row = min(matching, key=lambda r: (r.priority, r.id))
    impl = get_implementation(row.implementation)
    if impl.client_factory is None:
        raise NoDownloadClientError(
            f"download client {impl.name!r} for protocol {protocol!r} has no "
            "runnable client wired yet; the grab stays retryable"
        )
    settings_model = load_settings(row.implementation, row.settings)
    mappings = await load_mappings(db, row.id)
    ctx = ClientBuildContext(
        row=row,
        settings=settings_model,
        db=db,
        http_factory=http_factory,
        backoff=backoff,
        mappings=mappings,
        app_settings=app_settings,
    )
    return impl.client_factory(ctx)


async def resolve_client_for_grab(
    db,
    request: GrabReleaseCommand,
    *,
    http_factory,
    backoff,
    app_settings=None,
) -> DownloadClient:
    """Resolve the client for one grab, deriving its protocol first (FRG-DL-002)."""
    protocol = await protocol_for_grab(db, request)
    return await resolve_client_for(
        db,
        protocol,
        http_factory=http_factory,
        backoff=backoff,
        app_settings=app_settings,
    )


__all__ = [
    "protocol_for_grab",
    "protocol_for_indexer",
    "resolve_client_for",
    "resolve_client_for_grab",
]
