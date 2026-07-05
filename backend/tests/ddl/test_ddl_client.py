"""The DDL DownloadClient behind the common abstraction (FRG-DDL-001)."""

from __future__ import annotations

import httpx
import pytest

from foragerr.ddl.client import DdlClient
from foragerr.ddl.queue import STATUS_COMPLETED
from foragerr.downloads.clients.base import ClientItem, ClientItemStatus, DownloadClient
from foragerr.downloads.models import DdlQueueRow
from foragerr.downloads.settings import BuiltinDdlSettings
from foragerr.search_ops.grab import GrabReleaseCommand
from ddl_support import make_factory


def _client(tmp_path, db) -> DdlClient:
    factory, _ = make_factory(tmp_path, lambda req: httpx.Response(200))
    return DdlClient(
        BuiltinDdlSettings(), factory, db=db, config_dir=tmp_path
    )


def _grab(**kw) -> GrabReleaseCommand:
    return GrabReleaseCommand(
        indexer_id=kw.get("indexer_id", 1),
        guid=kw.get("guid", "https://getcomics.org/comic/x/"),
        link=kw.get("link", "https://getcomics.org/comic/x/"),
        title=kw.get("title", "Example Comic 1"),
        size_bytes=kw.get("size_bytes", 1000),
        series_id=kw.get("series_id"),
        issue_id=kw.get("issue_id", 555),
    )


@pytest.mark.req("FRG-DDL-001")
def test_ddl_client_satisfies_the_download_client_protocol(tmp_path, db):
    client = _client(tmp_path, db)
    assert isinstance(client, DownloadClient)  # runtime_checkable protocol


@pytest.mark.req("FRG-DDL-001")
async def test_download_returns_id_and_enqueues_a_queue_row(tmp_path, db):
    client = _client(tmp_path, db)
    download_id = await client.download(_grab())
    assert download_id.startswith("ddl-")
    async with db.read_session() as session:
        row = await session.get(DdlQueueRow, 1)
    assert row.download_id == download_id
    assert row.post_url == "https://getcomics.org/comic/x/"
    assert row.issue_id == 555  # provenance identity carried onto the queue row


@pytest.mark.req("FRG-DDL-001")
async def test_get_items_projects_queue_rows_into_client_items(tmp_path, db):
    client = _client(tmp_path, db)
    download_id = await client.download(_grab())
    items = await client.get_items()
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, ClientItem)
    assert item.download_id == download_id
    assert item.status is ClientItemStatus.QUEUED
    assert item.category == "ddl"


@pytest.mark.req("FRG-DDL-013")
async def test_completed_item_projects_output_path_for_import_handoff(tmp_path, db):
    client = _client(tmp_path, db)
    download_id = await client.download(_grab())
    # Simulate the engine completing the item (the tracking area then moves it
    # to import_pending off this COMPLETED projection).
    async with db.write_session() as session:
        row = await session.get(DdlQueueRow, 1)
        row.status = STATUS_COMPLETED
        row.output_path = str(tmp_path / "ddl-staging" / "Example 1 [__555__].cbz")
        row.bytes_received = row.expected_size or 1000
    items = await client.get_items()
    item = next(i for i in items if i.download_id == download_id)
    assert item.status is ClientItemStatus.COMPLETED
    assert item.output_path and "[__555__]" in item.output_path
    assert item.remaining_size == 0


@pytest.mark.req("FRG-DDL-001")
async def test_remove_deletes_the_queue_row(tmp_path, db):
    client = _client(tmp_path, db)
    await client.download(_grab())
    items = await client.get_items()
    await client.remove(items[0], delete_data=True)
    assert await client.get_items() == []
