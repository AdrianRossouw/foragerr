"""FRG-DL-011/007 — a transient client outage must NOT blocklist + re-grab the
whole in-flight queue.

Regression for the P0 bug where ``reconcile_downloads`` built ``seen`` from
observations alone, so one missed SAB poll promoted EVERY ``downloading`` row to
``failed_pending`` regardless of which client owned it — a blocklist + auto
re-search storm on a blip. The vanished check now fires only for a client that
was SUCCESSFULLY polled this cycle.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from foragerr.downloads.clients.base import ClientItemStatus
from foragerr.downloads.errors import DownloadClientUnreachableError
from foragerr.downloads.state import TrackedDownloadState
from foragerr.downloads.tracking import (
    collect_observations,
    process_failures,
    reconcile_downloads,
)
from tracking_support import (
    FakeClient,
    blocklist_rows,
    fake_row,
    insert_grab_history,
    insert_tracked,
    make_item,
    tracked_by_download_id,
    FakeCommands,
)


class _BoomClient(FakeClient):
    async def get_items(self):
        raise DownloadClientUnreachableError("SAB unreachable this cycle")


@pytest.mark.req("FRG-DL-011")
async def test_unreachable_client_does_not_vanish_its_in_flight_downloads(db):
    # An in-flight SAB download (client 1) and a genuinely-gone item from a
    # healthy DDL client (client 2).
    await insert_grab_history(db, download_id="inflight", series_id=1, issue_id=10, client_id=1)
    await insert_tracked(
        db, download_id="inflight", state=TrackedDownloadState.DOWNLOADING,
        client_id=1, series_id=1, issue_id=10,
    )
    await insert_grab_history(db, download_id="gone", series_id=2, issue_id=20, client_id=2)
    await insert_tracked(
        db, download_id="gone", state=TrackedDownloadState.DOWNLOADING,
        client_id=2, series_id=2, issue_id=20,
    )

    boom = _BoomClient([])  # SAB raises: client 1 NOT polled this cycle
    healthy = FakeClient([])  # DDL polled fine, its item is genuinely absent
    polled, obs = await collect_observations(
        [
            (fake_row(client_id=1, name="SAB"), boom),
            (fake_row(client_id=2, name="DDL", protocol="ddl"), healthy),
        ]
    )
    assert polled == {2}  # only the reachable client was polled

    await reconcile_downloads(db, obs, polled_client_ids=polled)

    # The unreachable client's in-flight row is untouched...
    inflight = await tracked_by_download_id(db, "inflight")
    assert inflight.state == TrackedDownloadState.DOWNLOADING.value
    # ...but a genuinely vanished item from a POLLED client still fails.
    gone = await tracked_by_download_id(db, "gone")
    assert gone.state == TrackedDownloadState.FAILED_PENDING.value

    # No blocklist / re-search for the in-flight (unreachable) item.
    commands = FakeCommands()
    await process_failures(db, commands=commands, settings=SimpleNamespace(auto_redownload_failed=True))
    blocks = await blocklist_rows(db)
    assert {b.issue_id for b in blocks} == {20}  # only the genuinely-gone item
    enqueued_issues = {(p[1].get("series_id"), p[1].get("issue_id")) for p in commands.enqueued}
    assert (1, 10) not in enqueued_issues  # the in-flight item is never re-searched
