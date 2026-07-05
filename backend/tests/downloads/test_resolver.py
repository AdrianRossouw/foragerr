"""FRG-DL-002 — client configuration + protocol-matched grab dispatch."""

from __future__ import annotations

import datetime as dt

import pytest

from foragerr.downloads.clients.sabnzbd import SabnzbdClient
from foragerr.downloads.errors import NoDownloadClientError
from foragerr.downloads.repo import create_download_client
from foragerr.downloads.resolver import (
    protocol_for_grab,
    protocol_for_indexer,
    resolve_client_for,
)
from foragerr.indexers.models import IndexerRow
from foragerr.providers.backoff import ProviderBackoff
from foragerr.search_ops.grab import GrabReleaseCommand
from downloads_support import SabFixture, make_sab_factory, sab_settings


async def _add_indexer(db, *, name: str, protocol: str) -> int:
    """Insert a bare indexer/provider row carrying just a protocol column."""
    async with db.write_session() as session:
        row = IndexerRow(
            name=name,
            implementation="newznab",
            protocol=protocol,
            priority=25,
            enabled=True,
            enable_rss=True,
            enable_auto=True,
            enable_interactive=True,
            settings="{}",
            added_at=dt.datetime(2026, 1, 1),
        )
        session.add(row)
        await session.flush()
        return row.id


async def _add_sab_client(db, *, name: str = "SAB", enabled: bool = True, priority: int = 25):
    return await create_download_client(
        db,
        name=name,
        implementation="sabnzbd",
        settings=sab_settings(),
        priority=priority,
        enabled=enabled,
    )


def _infra(tmp_path, db):
    factory, _ = make_sab_factory(tmp_path, SabFixture())
    return factory, ProviderBackoff(db)


@pytest.mark.req("FRG-DL-002")
async def test_protocol_is_derived_from_the_indexer_row(db):
    usenet_id = await _add_indexer(db, name="DogNZB", protocol="usenet")
    ddl_id = await _add_indexer(db, name="GetComics", protocol="ddl")
    assert await protocol_for_indexer(db, usenet_id) == "usenet"
    assert await protocol_for_indexer(db, ddl_id) == "ddl"
    # ...and via a GrabReleaseCommand carrying only indexer_id (not protocol).
    grab = GrabReleaseCommand(
        indexer_id=usenet_id, guid="g", link="https://idx.test/nzb/1", title="t"
    )
    assert await protocol_for_grab(db, grab) == "usenet"


@pytest.mark.req("FRG-DL-002")
async def test_usenet_release_routes_to_the_sabnzbd_client(tmp_path, db):
    await _add_sab_client(db)
    factory, backoff = _infra(tmp_path, db)
    client = await resolve_client_for(
        db, "usenet", http_factory=factory, backoff=backoff
    )
    assert isinstance(client, SabnzbdClient)


@pytest.mark.req("FRG-DL-002")
async def test_ddl_protocol_resolves_to_the_ddl_client_once_the_area_is_present(
    tmp_path, db
):
    # With the ddl area imported, its factory is wired onto the ``ddl``
    # implementation, so the ddl protocol resolves to a concrete DdlClient —
    # "just another client" (FRG-DL-002 / FRG-DDL-001).
    import foragerr.ddl  # noqa: F401 — registers the DDL client factory
    from foragerr.ddl.client import DdlClient
    from foragerr.downloads.settings import BuiltinDdlSettings

    await create_download_client(
        db, name="DDL", implementation="ddl", settings=BuiltinDdlSettings()
    )
    factory, backoff = _infra(tmp_path, db)
    client = await resolve_client_for(
        db, "ddl", http_factory=factory, backoff=backoff
    )
    assert isinstance(client, DdlClient)


@pytest.mark.req("FRG-DL-002")
async def test_no_enabled_client_for_protocol_is_typed_retryable(tmp_path, db):
    await _add_sab_client(db, enabled=False)  # present but disabled
    factory, backoff = _infra(tmp_path, db)
    with pytest.raises(NoDownloadClientError):
        await resolve_client_for(db, "usenet", http_factory=factory, backoff=backoff)


@pytest.mark.req("FRG-DL-002")
async def test_lowest_priority_value_wins_among_enabled_clients(tmp_path, db):
    await _add_sab_client(db, name="Secondary", priority=50)
    preferred = await _add_sab_client(db, name="Primary", priority=1)
    factory, backoff = _infra(tmp_path, db)
    client = await resolve_client_for(
        db, "usenet", http_factory=factory, backoff=backoff
    )
    # Both are SAB; assert selection picked the priority-1 row's client id.
    assert client._client_id == preferred.id
