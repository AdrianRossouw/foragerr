"""Import-visibility stall memory + health escalation (FRG-DL-015).

The Die-Loaded stall (rig finding #1): a download the client keeps reporting as
COMPLETED whose files the importer cannot see. Tracking re-queues it as
``import_pending`` every cycle, the drain blocks it again, and neither the row
nor health ever escalates — the loop is honest per cycle and blind over time.

These tests drive the REAL two-command loop (``reconcile_downloads`` +
``process_imports``), not a hand-rolled state flip, because the whole question is
whether the memory survives a reset written by a different module.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from foragerr.config import Settings
from foragerr.downloads.clients.base import ClientItemStatus
from foragerr.downloads.imports import (
    NO_IMPORTABLE_FILES_MESSAGE,
    is_visibility_stall,
    process_imports,
)
from foragerr.downloads.state import TrackedDownloadState
from foragerr.downloads.tracking import ClientObservation, decode_messages, reconcile_downloads
from foragerr.health import HealthService

from importer._archives import make_corrupt  # tests/importer is a package
from test_process_imports import make_large_cbz  # tests/downloads is on the path
from tracking_support import insert_grab_history, make_item, seed_library, tracked_by_download_id

_START = dt.datetime(2026, 7, 28, 9, 0, 0)


class _StubScheduler:
    async def status(self):  # pragma: no cover - health needs it to be quiet
        return []


def _obs(item, *, client_id: int | None = None):
    return ClientObservation(
        client_id=client_id, client_name="SAB", protocol="usenet", item=item
    )


async def _cycle(db, *, download_id: str, output_path: Path, now: dt.datetime) -> None:
    """One real minute of the loop: the client still says COMPLETED, tracking
    reconciles, the drain attempts the import."""
    item = make_item(
        download_id,
        status=ClientItemStatus.COMPLETED,
        output_path=str(output_path),
        remaining_size=0,
    )
    await reconcile_downloads(db, [_obs(item)], polled_client_ids={None}, now=now)
    await process_imports(db, None, now=now)


def _health(db, tmp_path, **settings_kw) -> HealthService:
    return HealthService(
        db,
        Settings(config_dir=db.db_path.parent, **settings_kw),
        scheduler=_StubScheduler(),
    )


async def _stall_component(service: HealthService):
    return next(
        (c for c in await service.component_view() if c.component == "downloads-stalled"),
        None,
    )


# --- the loop: the count accrues THROUGH the ping-pong -----------------------


@pytest.mark.req("FRG-DL-015")
async def test_stall_count_accrues_through_the_completed_ping_pong(db, tmp_path):
    """The untested loop: five real reconcile+drain cycles against a path that
    never becomes visible. Tracking resets the row to ``import_pending`` between
    every drain — the counter must not notice."""
    series_id, issue_id = await seed_library(db, tmp_path)
    invisible = tmp_path / "downloads" / "never-mounted"
    await insert_grab_history(
        db, download_id="stall1", series_id=series_id, issue_id=issue_id, client_id=None
    )

    for n in range(1, 6):
        await _cycle(
            db,
            download_id="stall1",
            output_path=invisible,
            now=_START + dt.timedelta(minutes=n - 1),
        )
        row = await tracked_by_download_id(db, "stall1")
        # Each individual cycle stays honest: blocked, with the real reason.
        assert row.state == TrackedDownloadState.IMPORT_BLOCKED.value
        assert decode_messages(row.status_messages) == [NO_IMPORTABLE_FILES_MESSAGE]
        # ...while the memory accumulates across them.
        assert row.import_stall_count == n
        # Stamped ONCE, at the first stall — not moved forward by the retries.
        assert row.first_stalled_at == _START


@pytest.mark.req("FRG-DL-015")
async def test_the_tracking_requeue_does_not_clear_the_memory(db, tmp_path):
    """The reset that would mask the count, isolated: a reconcile between drains
    genuinely moves the row back to ``import_pending`` and leaves both columns."""
    series_id, issue_id = await seed_library(db, tmp_path)
    invisible = tmp_path / "downloads" / "never-mounted"
    await insert_grab_history(
        db, download_id="stall2", series_id=series_id, issue_id=issue_id, client_id=None
    )
    await _cycle(db, download_id="stall2", output_path=invisible, now=_START)
    assert (await tracked_by_download_id(db, "stall2")).import_stall_count == 1

    # The re-queue on its own (no drain behind it).
    await reconcile_downloads(
        db,
        [
            _obs(
                make_item(
                    "stall2",
                    status=ClientItemStatus.COMPLETED,
                    output_path=str(invisible),
                    remaining_size=0,
                )
            )
        ],
        polled_client_ids={None},
        now=_START + dt.timedelta(minutes=1),
    )

    row = await tracked_by_download_id(db, "stall2")
    assert row.state == TrackedDownloadState.IMPORT_PENDING.value  # really reset
    assert row.import_stall_count == 1  # ...and the memory really survived it
    assert row.first_stalled_at == _START


# --- health escalation ------------------------------------------------------


@pytest.mark.req("FRG-DL-015")
async def test_health_degrades_only_past_the_threshold_then_clears(db, tmp_path):
    series_id, issue_id = await seed_library(db, tmp_path)
    invisible = tmp_path / "downloads" / "never-mounted"
    await insert_grab_history(
        db, download_id="stall3", series_id=series_id, issue_id=issue_id, client_id=None
    )
    service = _health(db, tmp_path)  # default threshold 5

    for n in range(1, 5):
        await _cycle(
            db,
            download_id="stall3",
            output_path=invisible,
            now=_START + dt.timedelta(minutes=n - 1),
        )
        assert await _stall_component(service) is None, f"escalated early at {n}"

    await _cycle(
        db, download_id="stall3", output_path=invisible, now=_START + dt.timedelta(minutes=4)
    )
    component = await _stall_component(service)
    assert component is not None
    assert component.state == "degraded"
    assert "1 completed download(s)" in component.message
    assert "5+ consecutive" in component.message
    assert _START.isoformat() in component.message  # the OLDEST stall, not the newest
    assert "path mapping" in component.remediation
    # It is a real warning, not just a view row.
    assert any(w.source == "downloads-stalled" for w in await service.warnings())

    # Real progress: the files become visible and the import succeeds.
    make_large_cbz(invisible / "Spawn 001 (2024).cbz")
    await _cycle(
        db, download_id="stall3", output_path=invisible, now=_START + dt.timedelta(minutes=5)
    )
    row = await tracked_by_download_id(db, "stall3")
    assert row.state == TrackedDownloadState.IMPORTED.value
    assert row.import_stall_count == 0
    assert row.first_stalled_at is None
    assert await _stall_component(service) is None


@pytest.mark.req("FRG-DL-015")
async def test_threshold_is_configurable_and_floored_at_two(db, tmp_path):
    series_id, issue_id = await seed_library(db, tmp_path)
    invisible = tmp_path / "downloads" / "never-mounted"
    await insert_grab_history(
        db, download_id="stall4", series_id=series_id, issue_id=issue_id, client_id=None
    )
    service = _health(db, tmp_path, import_stall_threshold_cycles=2)

    await _cycle(db, download_id="stall4", output_path=invisible, now=_START)
    assert await _stall_component(service) is None  # one cycle is never an alarm
    await _cycle(
        db,
        download_id="stall4",
        output_path=invisible,
        now=_START + dt.timedelta(minutes=1),
    )
    assert (await _stall_component(service)).state == "degraded"

    # The floor is a floor: a configured 1 is rejected outright, so no
    # deployment can turn every first blocked cycle into a health warning.
    with pytest.raises(ValueError):
        Settings(config_dir=db.db_path.parent, import_stall_threshold_cycles=1)


@pytest.mark.req("FRG-DL-015")
async def test_the_component_aggregates_rather_than_one_line_per_row(db, tmp_path):
    """A bad mount stalls the whole queue; health must stay one line."""
    series_id, issue_id = await seed_library(db, tmp_path)
    invisible = tmp_path / "downloads" / "never-mounted"
    for dl in ("agg1", "agg2", "agg3"):
        await insert_grab_history(
            db, download_id=dl, series_id=series_id, issue_id=issue_id, client_id=None
        )
    service = _health(db, tmp_path, import_stall_threshold_cycles=2)

    for n in range(2):
        now = _START + dt.timedelta(minutes=n)
        await reconcile_downloads(
            db,
            [
                _obs(
                    make_item(
                        dl,
                        status=ClientItemStatus.COMPLETED,
                        output_path=str(invisible),
                        remaining_size=0,
                    )
                )
                for dl in ("agg1", "agg2", "agg3")
            ],
            polled_client_ids={None},
            now=now,
        )
        await process_imports(db, None, now=now)

    components = [
        c for c in await service.component_view() if c.component == "downloads-stalled"
    ]
    assert len(components) == 1
    assert "3 completed download(s)" in components[0].message


# --- what does and does not count as a stall --------------------------------


@pytest.mark.req("FRG-DL-015")
def test_only_the_no_importable_files_shape_is_a_visibility_stall():
    """A blocked-with-reasons or corrupt outcome PROVES the path is visible, so
    it resets the memory rather than extending it."""
    assert is_visibility_stall([]) is True
    assert is_visibility_stall([], no_output=True) is True
    assert is_visibility_stall(["some-outcome"]) is False  # type: ignore[list-item]
    assert is_visibility_stall(["some-outcome"], no_output=True) is True  # type: ignore[list-item]


@pytest.mark.req("FRG-DL-015")
async def test_a_bad_but_VISIBLE_file_resets_the_memory(db, tmp_path):
    """A corrupt archive is a RELEASE problem, not a path problem: the drain
    demonstrably saw the file, so the visibility streak ends even though the
    import did not succeed."""
    series_id, issue_id = await seed_library(db, tmp_path)
    folder = tmp_path / "downloads" / "Spawn.001"
    await insert_grab_history(
        db, download_id="stall5", series_id=series_id, issue_id=issue_id, client_id=None
    )
    await _cycle(db, download_id="stall5", output_path=folder, now=_START)
    stalled = await tracked_by_download_id(db, "stall5")
    assert stalled.import_stall_count == 1
    assert decode_messages(stalled.status_messages) == [NO_IMPORTABLE_FILES_MESSAGE]

    # The path resolves, but what is under it is junk.
    make_corrupt(folder / "Spawn 001 (2024).cbz")
    await _cycle(
        db,
        download_id="stall5",
        output_path=folder,
        now=_START + dt.timedelta(minutes=1),
    )

    row = await tracked_by_download_id(db, "stall5")
    assert row.state == TrackedDownloadState.FAILED.value  # a release verdict
    assert row.import_stall_count == 0
    assert row.first_stalled_at is None
