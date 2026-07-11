"""One-time credits backfill: startup trigger, marker semantics, force-run
(FRG-CRTR-003).

Drives the real ``creators-backfill`` command + startup hook against a migrated
database. The command fans a deduplicated ``refresh-series`` per library series;
these tests assert the startup auto-run happens once (marker-gated), an empty
library short-circuits to just the marker, a manual force-run runs despite the
marker, and the run lands a job-history row like any command.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select, text

# Importing the library flows registers the ``refresh-series`` command type the
# backfill fans out to (matching the production app.py wiring); without it the
# handler's ``enqueue("refresh-series", ...)`` would fail validation.
import foragerr.library.flows  # noqa: F401
from foragerr.creators.commands import (
    BACKFILL_MARKER_KEY,
    CREATORS_BACKFILL_STARTUP_TRIGGER,
    CREATORS_BACKFILL_TASK,
    CREATORS_BACKFILL_TRIGGERED_BY,
    creators_backfill_startup_hook,
    is_backfill_complete,
    register_creators_backfill_task,
)
from foragerr.db import CommandRow, JobHistoryRow, ScheduledTaskRow
from foragerr.db.first_run import APP_STATE_TABLE
from foragerr.library import repo


async def _make_series(db, root_folder_path: Path, format_profile_id: int, *, cv_volume_id: int) -> int:
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title=f"Series {cv_volume_id}",
            monitored=True,
            monitor_new_items="all",
            format_profile_id=format_profile_id,
            root_folder_id=(await repo.list_root_folders(session))[0].id,
            path=str(root_folder_path / f"series-{cv_volume_id}"),
        )
        return series.id


class _FakeScheduler:
    """A minimal scheduler double recording register_task + force_run, backed by
    the real ``scheduled_tasks`` table so the last_run stamp is observable."""

    def __init__(self, db):
        self._db = db
        self._defs: dict[str, dict] = {}

    async def register_task(self, *, name, command_name, interval_seconds, min_interval_seconds):
        self._defs[name] = {"command_name": command_name, "interval_seconds": interval_seconds}
        async with self._db.write_session() as session:
            row = await session.get(ScheduledTaskRow, name)
            if row is None:
                session.add(
                    ScheduledTaskRow(name=name, interval_seconds=interval_seconds, last_run=None)
                )


class _AppState:
    def __init__(self, db, commands, scheduler):
        self.db = db
        self.commands = commands
        self.scheduler = scheduler


class _App:
    def __init__(self, db, commands, scheduler):
        self.state = _AppState(db, commands, scheduler)


async def _queued_refresh_ids(db) -> list[int]:
    async with db.read_session() as session:
        rows = (
            await session.execute(
                select(CommandRow).where(CommandRow.name == "refresh-series")
            )
        ).scalars().all()
        return [r.id for r in rows]


async def _run_backfill_handler(db, commands):
    """Run the backfill command handler once directly (no worker loop)."""
    from foragerr.commands.registry import get_handler, parse_command

    command = parse_command(CREATORS_BACKFILL_TASK, None)
    return await get_handler(CREATORS_BACKFILL_TASK)(command, commands.context)


# --- FRG-CRTR-003 -----------------------------------------------------------


@pytest.mark.req("FRG-CRTR-003")
async def test_startup_enqueues_backfill_once_and_marker_gates_reruns(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=2)
    app = _App(db, commands, _FakeScheduler(db))

    # First startup: marker unset + library non-empty -> the backfill command is
    # enqueued (its own trigger recorded), but NOT the marker yet (the handler
    # sets it on completion).
    await creators_backfill_startup_hook(app)
    async with db.read_session() as session:
        backfill_cmds = (
            await session.execute(
                select(CommandRow).where(CommandRow.name == CREATORS_BACKFILL_TASK)
            )
        ).scalars().all()
    assert len(backfill_cmds) == 1
    assert backfill_cmds[0].triggered_by == CREATORS_BACKFILL_STARTUP_TRIGGER
    assert not await is_backfill_complete(db)

    # Run the handler: it fans a deduplicated refresh-series per series and sets
    # the marker on success.
    summary = await _run_backfill_handler(db, commands)
    assert "2 library series" in summary
    refreshes = await _queued_refresh_ids(db)
    assert len(refreshes) == 2  # one per series, all triggered by the backfill
    async with db.read_session() as session:
        triggers = {
            r.triggered_by
            for r in (
                await session.execute(
                    select(CommandRow).where(CommandRow.name == "refresh-series")
                )
            ).scalars().all()
        }
    assert triggers == {CREATORS_BACKFILL_TRIGGERED_BY}
    assert await is_backfill_complete(db)

    # Second startup (marker now set): no new backfill command is enqueued.
    await creators_backfill_startup_hook(app)
    async with db.read_session() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(CommandRow)
            .where(CommandRow.name == CREATORS_BACKFILL_TASK)
        )
    assert count == 1  # still the single original enqueue


@pytest.mark.req("FRG-CRTR-003")
async def test_backfill_refreshes_are_deduplicated(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)

    # A refresh for this series is already queued (e.g. from an add flow).
    await commands.enqueue("refresh-series", {"series_id": sid}, triggered_by="manual")

    await _run_backfill_handler(db, commands)

    # The backfill's enqueue dedups onto the existing queued refresh (FRG-SCHED-003).
    assert len(await _queued_refresh_ids(db)) == 1


@pytest.mark.req("FRG-CRTR-003")
async def test_empty_library_sets_marker_without_enqueuing(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    app = _App(db, commands, _FakeScheduler(db))
    await creators_backfill_startup_hook(app)

    # Empty library -> marker set, and NO backfill command was enqueued.
    assert await is_backfill_complete(db)
    async with db.read_session() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(CommandRow)
            .where(CommandRow.name == CREATORS_BACKFILL_TASK)
        )
    assert count == 0


@pytest.mark.req("FRG-CRTR-003")
async def test_force_run_works_despite_marker(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)

    # Pre-set the marker as if a prior backfill already completed.
    async with db.write_session() as session:
        await session.execute(
            text(f"INSERT INTO {APP_STATE_TABLE} (key, value) VALUES (:k, 'done')"),
            {"k": BACKFILL_MARKER_KEY},
        )
    assert await is_backfill_complete(db)

    # The handler never reads the marker: a force-run runs the (idempotent) work
    # regardless, enqueuing the refresh again.
    await _run_backfill_handler(db, commands)
    assert len(await _queued_refresh_ids(db)) == 1


@pytest.mark.req("FRG-CRTR-003")
async def test_registration_stamps_last_run_so_scheduler_never_auto_fires(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    scheduler = _FakeScheduler(db)
    await register_creators_backfill_task(scheduler, db)

    # A fresh task row's last_run is stamped (non-NULL) at registration, so the
    # interval scheduler's "last_run IS NULL -> due" tick never auto-fires it —
    # the marker-gated startup hook is the sole automatic trigger.
    async with db.read_session() as session:
        row = await session.get(ScheduledTaskRow, CREATORS_BACKFILL_TASK)
    assert row is not None
    assert row.last_run is not None


@pytest.mark.req("FRG-CRTR-003")
async def test_backfill_run_records_job_history(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """The backfill rides the command backbone: a full enqueue -> worker run lands
    a completed job-history row like any command (FRG-CRTR-003 / FRG-SCHED-008).

    Kept hermetic by running against an empty library, so the handler enqueues no
    ``refresh-series`` (which would otherwise reach the network) — the fan-out is
    covered by the other tests."""
    await commands.start()
    try:
        record = await commands.enqueue(
            CREATORS_BACKFILL_TASK, triggered_by=CREATORS_BACKFILL_STARTUP_TRIGGER
        )
        from conftest import eventually

        async def _completed():
            got = await commands.get(record.id)
            return got is not None and got.status == "completed"

        await eventually(_completed)
    finally:
        await commands.drain(grace_seconds=5.0)

    async with db.read_session() as session:
        history = (
            await session.execute(
                select(JobHistoryRow).where(JobHistoryRow.name == CREATORS_BACKFILL_TASK)
            )
        ).scalars().all()
    assert len(history) == 1
    assert history[0].outcome == "completed"
    assert history[0].triggered_by == CREATORS_BACKFILL_STARTUP_TRIGGER
    assert await is_backfill_complete(db)
