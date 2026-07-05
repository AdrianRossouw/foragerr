"""FRG-DL-001 — the DownloadClient protocol + uniform ClientItem contract."""

from __future__ import annotations

import inspect

import pytest

from foragerr.downloads.clients.base import (
    ClientItem,
    ClientItemStatus,
    ClientTestResult,
    DownloadClient,
)
from foragerr.downloads.clients.sabnzbd import SabnzbdClient
from foragerr.downloads.state import TrackedDownloadState
from downloads_support import SabFixture, history_slot, make_sab_client


@pytest.mark.req("FRG-DL-001")
def test_sabnzbd_satisfies_the_downloadclient_protocol(tmp_path, db):
    client = make_sab_client(tmp_path, SabFixture(), db)
    # runtime_checkable structural conformance + the exact method surface.
    assert isinstance(client, DownloadClient)
    for method in ("test", "download", "get_items", "remove", "mark_imported"):
        assert inspect.iscoroutinefunction(getattr(client, method))


@pytest.mark.req("FRG-DL-001")
def test_client_item_status_enum_is_exactly_the_common_set():
    assert {s.value for s in ClientItemStatus} == {
        "queued",
        "paused",
        "downloading",
        "completed",
        "failed",
        "warning",
    }


@pytest.mark.req("FRG-DL-001")
def test_tracked_download_state_enum_is_exactly_the_eight_states():
    assert [s.value for s in TrackedDownloadState] == [
        "downloading",
        "import_blocked",
        "import_pending",
        "importing",
        "imported",
        "failed_pending",
        "failed",
        "ignored",
    ]


@pytest.mark.req("FRG-DL-001")
def test_client_item_carries_the_uniform_typed_shape():
    item = ClientItem(
        download_id="nzo_1",
        title="Comic 001",
        category="comics",
        total_size=1024,
        remaining_size=512,
        estimated_time=30.0,
        output_path=None,
        status=ClientItemStatus.DOWNLOADING,
    )
    assert item.encrypted is False and item.reason is None
    assert item.total_size == 1024 and item.remaining_size == 512  # bytes


@pytest.mark.req("FRG-DL-001")
async def test_get_items_yields_uniform_client_items_from_native_shape(tmp_path, db):
    fixture = SabFixture()
    fixture.history_slots = [history_slot(nzo_id="nzo_done")]
    client = make_sab_client(tmp_path, fixture, db)
    items = await client.get_items()
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, ClientItem)
    assert item.download_id == "nzo_done"
    assert item.status is ClientItemStatus.COMPLETED
    assert isinstance(item.total_size, int) and isinstance(item.remaining_size, int)


@pytest.mark.req("FRG-DL-001")
def test_test_result_is_the_typed_contract():
    result = ClientTestResult(success=True, message="ok", version="4.3.2")
    assert result.success and result.version == "4.3.2" and result.warnings == ()


@pytest.mark.req("FRG-DL-001")
def test_from_context_builds_a_sabnzbd_client(tmp_path, db):
    # The registry factory path the resolver + test endpoint use.
    from foragerr.downloads.registry import ClientBuildContext, get_implementation
    from downloads_support import make_sab_factory, sab_settings

    class _Row:
        id = 3
        remove_completed_downloads = True

    factory, _ = make_sab_factory(tmp_path, SabFixture())
    from foragerr.providers.backoff import ProviderBackoff

    ctx = ClientBuildContext(
        row=_Row(),
        settings=sab_settings(),
        db=db,
        http_factory=factory,
        backoff=ProviderBackoff(db),
        mappings=[],
    )
    client = get_implementation("sabnzbd").client_factory(ctx)
    assert isinstance(client, SabnzbdClient)
