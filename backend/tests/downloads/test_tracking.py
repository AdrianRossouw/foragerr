"""FRG-DL-007 — tracked-download state machine, adoption, restart safety, events."""

from __future__ import annotations

import pytest

from foragerr.downloads.clients.base import ClientItemStatus
from foragerr.downloads.state import (
    TRACKED_STATUS_ERROR,
    TRACKED_STATUS_OK,
    TRACKED_STATUS_WARNING,
    TrackedDownloadState,
)
from foragerr.downloads.tracking import (
    ClientObservation,
    TrackedStateChanged,
    collect_observations,
    reconcile_downloads,
)
from foragerr.events import EventBus
from tracking_support import (
    FakeClient,
    fake_row,
    insert_grab_history,
    insert_tracked,
    make_item,
    seed_library,
    tracked_by_download_id,
)


def _obs(item, *, client_id=1, protocol="usenet") -> ClientObservation:
    return ClientObservation(
        client_id=client_id, client_name="SAB", protocol=protocol, item=item
    )


@pytest.mark.req("FRG-DL-007")
@pytest.mark.parametrize(
    "status,kwargs,expected_state,expected_status",
    [
        (ClientItemStatus.DOWNLOADING, {}, TrackedDownloadState.DOWNLOADING, TRACKED_STATUS_OK),
        (ClientItemStatus.QUEUED, {}, TrackedDownloadState.DOWNLOADING, TRACKED_STATUS_OK),
        (ClientItemStatus.PAUSED, {}, TrackedDownloadState.DOWNLOADING, TRACKED_STATUS_WARNING),
        (ClientItemStatus.COMPLETED, {"output_path": "/dl/x"}, TrackedDownloadState.IMPORT_PENDING, TRACKED_STATUS_OK),
        (ClientItemStatus.WARNING, {"reason": "check remote path mapping"}, TrackedDownloadState.IMPORT_BLOCKED, TRACKED_STATUS_WARNING),
        (ClientItemStatus.FAILED, {"reason": "boom"}, TrackedDownloadState.FAILED_PENDING, TRACKED_STATUS_ERROR),
    ],
)
async def test_state_machine_matrix(
    db, status, kwargs, expected_state, expected_status
):
    await insert_grab_history(db, download_id="d1", series_id=1, issue_id=10)
    item = make_item("d1", status=status, **kwargs)
    await reconcile_downloads(db, [_obs(item)])
    row = await tracked_by_download_id(db, "d1")
    assert row.state == expected_state.value
    assert row.status == expected_status
    assert row.series_id == 1 and row.issue_id == 10  # matched by download_id


@pytest.mark.req("FRG-DL-007")
async def test_encrypted_item_becomes_failed_pending(db):
    await insert_grab_history(db, download_id="enc", series_id=1, issue_id=10)
    item = make_item("enc", status=ClientItemStatus.FAILED, encrypted=True, reason="password")
    await reconcile_downloads(db, [_obs(item)])
    row = await tracked_by_download_id(db, "enc")
    assert row.state == TrackedDownloadState.FAILED_PENDING.value
    assert row.encrypted is True


@pytest.mark.req("FRG-DL-007")
async def test_unmatched_item_adopted_via_issue_id_tag(db, tmp_path):
    series_id, issue_id = await seed_library(db, tmp_path)
    # No grab_history: the [__id__] tag must win and adopt onto the real issue.
    item = make_item("orphan", title=f"Spawn 1 (2024) [__{issue_id}__]")
    await reconcile_downloads(db, [_obs(item)])
    row = await tracked_by_download_id(db, "orphan")
    assert row.series_id == series_id and row.issue_id == issue_id


@pytest.mark.req("FRG-DL-007")
async def test_unmatched_unknown_item_is_recorded_not_crashing(db):
    item = make_item("mystery", title="Totally Unknown Thing 99")
    await reconcile_downloads(db, [_obs(item)])  # must not raise
    row = await tracked_by_download_id(db, "mystery")
    assert row is not None
    assert row.series_id is None and row.issue_id is None


@pytest.mark.req("FRG-DL-007")
async def test_transitions_are_restart_safe_and_persist(db):
    await insert_grab_history(db, download_id="rs", series_id=1, issue_id=10)
    # cycle 1: downloading
    await reconcile_downloads(db, [_obs(make_item("rs", status=ClientItemStatus.DOWNLOADING))])
    row = await tracked_by_download_id(db, "rs")
    assert row.state == TrackedDownloadState.DOWNLOADING.value
    # cycle 2 (a fresh reconcile == a fresh process reading persisted state):
    # the completed item advances the persisted row to import_pending.
    await reconcile_downloads(db, [_obs(make_item("rs", status=ClientItemStatus.COMPLETED, output_path="/dl/x"))])
    row = await tracked_by_download_id(db, "rs")
    assert row.state == TrackedDownloadState.IMPORT_PENDING.value


@pytest.mark.req("FRG-DL-007")
async def test_import_pending_is_not_regressed_to_downloading(db):
    await insert_grab_history(db, download_id="ip", series_id=1, issue_id=10)
    await insert_tracked(
        db, download_id="ip", state=TrackedDownloadState.IMPORT_PENDING,
        series_id=1, issue_id=10,
    )
    # A stale queue slot still calling it "downloading" must not drag it back.
    await reconcile_downloads(db, [_obs(make_item("ip", status=ClientItemStatus.DOWNLOADING))])
    row = await tracked_by_download_id(db, "ip")
    assert row.state == TrackedDownloadState.IMPORT_PENDING.value


@pytest.mark.req("FRG-DL-007")
async def test_vanished_download_becomes_failed_pending(db):
    await insert_tracked(
        db, download_id="gone", state=TrackedDownloadState.DOWNLOADING,
        series_id=1, issue_id=10,
    )
    # No client reports it this cycle -> vanished -> failure path.
    await reconcile_downloads(db, [])
    row = await tracked_by_download_id(db, "gone")
    assert row.state == TrackedDownloadState.FAILED_PENDING.value


@pytest.mark.req("FRG-DL-007")
async def test_state_transitions_emit_events(db):
    bus = EventBus()
    seen: list[TrackedStateChanged] = []
    bus.subscribe(TrackedStateChanged, seen.append)
    db.event_publisher = bus.publish

    await insert_grab_history(db, download_id="ev", series_id=1, issue_id=10)
    await reconcile_downloads(db, [_obs(make_item("ev", status=ClientItemStatus.DOWNLOADING))])
    await reconcile_downloads(db, [_obs(make_item("ev", status=ClientItemStatus.COMPLETED, output_path="/x"))])

    states = [e.state for e in seen]
    assert TrackedDownloadState.DOWNLOADING.value in states
    assert TrackedDownloadState.IMPORT_PENDING.value in states


@pytest.mark.req("FRG-DL-007")
async def test_collect_observations_isolates_one_failing_client(db):
    from foragerr.downloads.errors import DownloadClientUnreachableError

    class _Boom(FakeClient):
        async def get_items(self):
            raise DownloadClientUnreachableError("down")

    good = FakeClient([make_item("ok1", status=ClientItemStatus.DOWNLOADING)])
    obs = await collect_observations(
        [
            (fake_row(client_id=1, name="Good"), good),
            (fake_row(client_id=2, name="Bad"), _Boom([])),
        ]
    )
    # The healthy client's item still surfaces; the failing client is skipped.
    assert [o.item.download_id for o in obs] == ["ok1"]
