"""FRG-DL-003 — SABnzbd server-side NZB fetch, validation, addfile upload.

Also covers FRG-DL-002 scenario 3: a client unreachable at grab surfaces a typed
retryable failure, never a silent drop.
"""

from __future__ import annotations

import pytest

from foragerr.downloads.errors import (
    DownloadClientUnreachableError,
    GrabValidationError,
)
from foragerr.providers.backoff import PROVIDER_DOWNLOAD_CLIENT, PROVIDER_INDEXER
from foragerr.search_ops.grab import GrabReleaseCommand
from downloads_support import (
    EMPTY_NZB,
    JUNK_NZB,
    NO_SEGMENT_NZB,
    NZB_URL,
    SAB_BASE,
    SabFixture,
    make_sab_client,
)

INDEXER_ID = 7


def _grab() -> GrabReleaseCommand:
    return GrabReleaseCommand(
        indexer_id=INDEXER_ID,
        guid="guid-1",
        link=NZB_URL,
        title="Saga 001 (2024)",
        size_bytes=52_428_800,
    )


@pytest.mark.req("FRG-DL-003")
async def test_server_side_fetch_then_addfile_records_nzo_id(tmp_path, db):
    fixture = SabFixture()
    fixture.addfile_nzo_ids = ["SABnzbd_nzo_xyz"]
    client = make_sab_client(tmp_path, fixture, db)

    download_id = await client.download(_grab())

    assert download_id == "SABnzbd_nzo_xyz"
    # The NZB was fetched from the indexer host (external), NOT handed to SAB
    # with indexer credentials; the addfile then hit the SAB host.
    hosts = [(r.url.host, r.url.params.get("mode")) for r in fixture.requests]
    assert ("idx.test", None) in hosts  # external NZB fetch
    assert "addfile" in fixture.modes
    addfile_req = next(r for r in fixture.requests if r.url.params.get("mode") == "addfile")
    assert addfile_req.url.params.get("cat") == "comics"
    assert b"segment" in addfile_req.content  # the validated NZB body was posted


@pytest.mark.req("FRG-DL-003")
async def test_local_service_egress_reaches_the_private_sab_host(tmp_path, db):
    # SAB_BASE is an RFC-1918 address: the request only succeeds because the SAB
    # calls use the local-service profile (external would refuse it).
    assert SAB_BASE.startswith("http://10.")
    fixture = SabFixture()
    client = make_sab_client(tmp_path, fixture, db)
    await client.download(_grab())
    addfile_req = next(r for r in fixture.requests if r.url.params.get("mode") == "addfile")
    assert addfile_req.url.host == "10.1.2.3"


@pytest.mark.req("FRG-DL-003")
@pytest.mark.parametrize("bad", [EMPTY_NZB, JUNK_NZB, NO_SEGMENT_NZB])
async def test_invalid_nzb_fails_grab_and_is_never_posted(tmp_path, db, bad):
    fixture = SabFixture()
    fixture.nzb_bytes = bad
    client = make_sab_client(tmp_path, fixture, db)
    with pytest.raises(GrabValidationError):
        await client.download(_grab())
    assert "addfile" not in fixture.modes  # never POSTed to SABnzbd


@pytest.mark.req("FRG-DL-003")
async def test_empty_nzo_id_response_is_a_grab_failure(tmp_path, db):
    fixture = SabFixture()
    fixture.addfile_nzo_ids = []  # SAB accepted nothing
    client = make_sab_client(tmp_path, fixture, db)
    with pytest.raises(GrabValidationError):
        await client.download(_grab())


@pytest.mark.req("FRG-DL-003")
async def test_nzb_fetch_failure_engages_the_indexer_backoff_ladder(tmp_path, db):
    fixture = SabFixture()
    fixture.nzb_status = 500  # indexer NZB fetch unavailable
    client = make_sab_client(tmp_path, fixture, db)
    with pytest.raises(DownloadClientUnreachableError):
        await client.download(_grab())
    assert "addfile" not in fixture.modes
    status = await client._backoff.status(PROVIDER_INDEXER, INDEXER_ID)
    assert status.failure_count >= 1  # ladder recorded the fetch failure


@pytest.mark.req("FRG-DL-002")
@pytest.mark.req("FRG-DL-003")
async def test_sab_unreachable_at_grab_is_typed_and_retryable(tmp_path, db):
    # FRG-DL-002 scenario 3: the client is unreachable at grab time -> a typed
    # failure (never a silent None), and the download-client ladder is engaged so
    # the grab stays retryable rather than lost.
    fixture = SabFixture()
    fixture.sab_status = 503
    client = make_sab_client(tmp_path, fixture, db, client_id=4)
    with pytest.raises(DownloadClientUnreachableError):
        await client.download(_grab())
    status = await client._backoff.status(PROVIDER_DOWNLOAD_CLIENT, 4)
    assert status.failure_count >= 1


@pytest.mark.req("FRG-DL-003")
async def test_indexer_already_backing_off_skips_the_fetch(tmp_path, db):
    fixture = SabFixture()
    client = make_sab_client(tmp_path, fixture, db)
    backoff = client._backoff
    await backoff.record_failure(PROVIDER_INDEXER, INDEXER_ID, reason="prior failure")
    with pytest.raises(DownloadClientUnreachableError):
        await client.download(_grab())
    # No NZB fetch was even attempted while backing off.
    assert all(r.url.host != "idx.test" for r in fixture.requests)
