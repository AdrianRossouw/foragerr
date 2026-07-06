"""Staged crash/restart fault-injection acceptance (FRG-NFR-007).

This module is the *acceptance* layer the m2-hardening-performance delta calls
for: it stages a simulated crash at each enumerated injection point, drops the
process (disposes the engine with no drain/close), reopens a **fresh**
``Database`` against the same on-disk file (the restart), and asserts the
FRG-NFR-007 recovery invariants — no acknowledged work lost, no duplicate
snatch, no double import.

It deliberately does NOT re-test the underlying mechanisms, which already have
tagged coverage elsewhere:

* the persisted command queue + orphan recovery — ``test_commands_recovery.py``
  (FRG-SCHED-002);
* the grab handler's ``(indexer_id, guid)`` idempotency guard —
  ``downloads/test_grab_live.py`` (FRG-DL-006/FRG-DL-002);
* ``gather`` skipping already-registered files —
  ``importer/test_library_source.py`` (FRG-IMP-023).

What is new here is the end-to-end **crash property tagged to FRG-NFR-007**:
each invariant is exercised as idempotent re-execution over committed
intermediate states across a fresh-``Database`` restart (engine dispose → fresh
``Database``/handler context on the persisted file), re-invoking the handler at
the staged point after the restart. That is what these tests actually drive —
not a real ``kill -9`` of a live OS process (no such soak matrix exists here).

FRG-NFR-007 is worded as *at-least-once execution and idempotent handlers (no
duplicate snatches or double imports)*, and its "re-snatching is idempotent"
scenario pins the invariant on durable state — *no duplicate grab or
tracked-download row*. Crucially the grab handler calls the side-effecting
``client.download()`` BEFORE its ``grab_history`` row commits, so a crash in
that window re-downloads on restart: the external snatch is genuinely
**at-least-once**. That duplicate snatch is the accepted, safe failure direction
(a marker-first ordering would instead LOSE grabs when a crash lands between the
marker write and the download). The tests below cover both the
already-committed window (the guard skips the re-download) and the real
pre-commit window (the re-download happens, but still exactly one durable
``grab_history`` row).
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from conftest import eventually, seed_series_issue
from foragerr.db import CommandRow, Database, JobHistoryRow, TERMINAL_STATUSES


async def _terminal(service, command_id: int):
    record = await service.get(command_id)
    return record if record and record.status in TERMINAL_STATUSES else None


# ---------------------------------------------------------------------------
# Injection point 1 — post-enqueue / mid-command crash: acknowledged commands
# survive the restart to a consistent state (no work item lost).
# ---------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-007")
async def test_staged_command_crash_recovers_queue_without_losing_work(
    migrated_dir, command_registry
):
    """Stage a crash with one command left ``started`` (killed mid-execution)
    and one left ``queued`` (enqueued, worker never ran) — the two persisted
    states a power loss can freeze a command in. After an unclean restart both
    are recovered to a terminal state, by identity, and recovery mints no
    phantom rows (queue integrity)."""
    from foragerr.commands import CommandService

    db_path = migrated_dir / "foragerr.db"

    # First process lifetime: enqueue two commands, never start the workers,
    # then stage the crash by freezing one row in `started` (a kill landing
    # mid-execution) while the other stays `queued` (a kill landing right after
    # the enqueue commit). Die without any drain/checkpoint.
    first_db = Database(db_path=db_path)
    first = CommandService(first_db)
    started_cmd = await first.enqueue("noop", {"note": "mid-execution"})
    queued_cmd = await first.enqueue("noop", {"note": "post-enqueue"})
    async with first_db.write_session() as session:
        row = await session.get(CommandRow, started_cmd.id)
        row.status = "started"
        row.started_at = row.queued_at
    await first_db.engine.dispose()  # simulated kill: no drain, no close()

    # Second (restarted) process: fresh Database + service over the persisted
    # file. Startup recovery re-queues the orphaned `started` command; both run
    # to completion — no acknowledged work item is lost.
    second_db = Database(db_path=db_path)
    second = CommandService(second_db, poll_interval=0.05)
    await second.start()
    try:
        assert (await eventually(lambda: _terminal(second, started_cmd.id))).status == "completed"
        assert (await eventually(lambda: _terminal(second, queued_cmd.id))).status == "completed"

        async with second_db.read_session() as session:
            rows = (await session.execute(select(CommandRow))).scalars().all()
        # Survival by identity: exactly the two original rows, no phantom
        # duplicate minted by recovery (a wipe-and-repopulate would fail this).
        assert {r.id for r in rows} == {started_cmd.id, queued_cmd.id}
        assert {r.status for r in rows} == {"completed"}

        # The interruption of the mid-execution command is recorded, so the
        # recovery is auditable rather than silent.
        async with second_db.read_session() as session:
            outcomes = (
                (
                    await session.execute(
                        select(JobHistoryRow.outcome).where(
                            JobHistoryRow.command_id == started_cmd.id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert "interrupted" in outcomes
    finally:
        await second.drain(1.0)
        await second_db.close()


# ---------------------------------------------------------------------------
# Injection point 2 — mid-download crash: re-snatching the same release after a
# restart is idempotent (no duplicate grab / tracked-download row).
# ---------------------------------------------------------------------------


class _CountingClient:
    """Download client stub that counts how many times ``download`` runs, so a
    re-snatch that should be skipped is observable as a non-increment."""

    def __init__(self, *, download_id="nzo-crash", client_id=3):
        self._download_id = download_id
        self._client_id = client_id
        self.calls = 0

    @property
    def client_id(self):
        return self._client_id

    async def download(self, request) -> str:
        self.calls += 1
        return self._download_id


def _patch_resolution(monkeypatch, *, client, protocol="usenet"):
    """Patch the grab handler's lazily-imported client resolution (mirrors
    ``downloads/test_grab_live.py``) so no real indexer/downloader is touched."""
    import foragerr.downloads as downloads_pkg
    import foragerr.downloads.resolver as resolver

    async def _protocol(db, request):
        return protocol

    async def _resolve(db, proto, **kwargs):
        return client

    monkeypatch.setattr(resolver, "protocol_for_grab", _protocol)
    monkeypatch.setattr(resolver, "resolve_client_for", _resolve)
    monkeypatch.setattr(downloads_pkg, "make_download_factory", lambda s: None)


@pytest.mark.req("FRG-NFR-007")
async def test_staged_download_crash_resnatch_is_idempotent(
    migrated_dir, monkeypatch
):
    """A grab commits ``client.download()`` before its ``grab_history`` row; a
    crash can freeze the ``grab-release`` command `started` after the download
    already happened. After the restart the orphaned command re-runs — and must
    NOT re-download the same release nor mint a second join-key row."""
    from foragerr.commands.service import HandlerContext, daemon_offload
    from foragerr.config import Settings
    from foragerr.downloads.models import GrabHistoryRow
    from foragerr.search_ops.grab import GrabReleaseCommand, _handle_grab_release

    db_path = migrated_dir / "foragerr.db"
    command = GrabReleaseCommand(
        indexer_id=7,
        guid="G-crash",
        link="https://idx.test/nzb/1",
        title="Spawn 001 (2024)",
        size_bytes=12345,
        series_id=1,
        issue_id=10,
        indexer_name="DogNZB",
    )

    class _Commands:  # records follow-up enqueues; no dedup needed here
        def __init__(self):
            self.enqueued = []

        async def enqueue(self, name, payload=None, *, priority=None, triggered_by="manual"):
            self.enqueued.append(name)
            return type("_Rec", (), {"id": len(self.enqueued)})()

    def _ctx(db):
        return HandlerContext(
            db=db,
            bus=None,
            settings=Settings(config_dir="/tmp"),
            offload=daemon_offload,
            commands=_Commands(),
        )

    async def _grab_history(db):
        async with db.read_session() as session:
            rows = (await session.execute(select(GrabHistoryRow))).scalars().all()
            for r in rows:
                session.expunge(r)
            return list(rows)

    client = _CountingClient(download_id="nzo-crash")
    _patch_resolution(monkeypatch, client=client)

    # First process lifetime: the grab downloads and records its join-key row,
    # then the process is killed (engine disposed) with the command notionally
    # still `started`.
    first_db = Database(db_path=db_path)
    await _handle_grab_release(command, _ctx(first_db))
    assert client.calls == 1  # downloaded once before the crash
    before = await _grab_history(first_db)
    assert len(before) == 1 and before[0].download_id == "nzo-crash"
    await first_db.engine.dispose()  # simulated kill

    # Restarted process: the SAME `started` command is re-run against a fresh
    # Database. The idempotency guard finds the persisted (indexer_id, guid) row
    # and resumes to the tracking hand-off WITHOUT re-downloading.
    second_db = Database(db_path=db_path)
    try:
        await _handle_grab_release(command, _ctx(second_db))
        assert client.calls == 1  # no re-download after the restart
        after = await _grab_history(second_db)
        # One grab_history row by identity — its download_id is the sole tracking
        # join key, so a single row is a single tracked download (no duplicate
        # snatch, no duplicate tracked-download row).
        assert len(after) == 1
        assert after[0].id == before[0].id
        assert after[0].download_id == "nzo-crash"
    finally:
        await second_db.close()


@pytest.mark.req("FRG-NFR-007")
async def test_staged_download_crash_before_commit_resnatches_at_least_once(
    migrated_dir, monkeypatch
):
    """The REAL duplicate-snatch window: a crash AFTER ``client.download()``
    returns but BEFORE the ``grab_history`` row commits. On restart the
    idempotency guard finds NO persisted ``(indexer_id, guid)`` row (it never
    committed), so it re-downloads — the external snatch is genuinely
    **at-least-once**.

    This is the ACCEPTED, safe failure mode. A marker-first ordering (write
    ``grab_history`` before downloading) would instead LOSE a grab when a crash
    lands between the marker and the download; the current ordering can only
    duplicate a snatch, never drop one. FRG-NFR-007 pins the invariant on
    durable state — *no duplicate grab / tracked-download row* — and that holds:
    exactly one ``grab_history`` row survives, written by the restart run."""
    from foragerr.commands.service import HandlerContext, daemon_offload
    from foragerr.config import Settings
    from foragerr.downloads.models import GrabHistoryRow
    import foragerr.search_ops.grab as grab_mod
    from foragerr.search_ops.grab import GrabReleaseCommand, _handle_grab_release

    db_path = migrated_dir / "foragerr.db"
    command = GrabReleaseCommand(
        indexer_id=7,
        guid="G-window",
        link="https://idx.test/nzb/2",
        title="Spawn 002 (2024)",
        size_bytes=2222,
        series_id=1,
        issue_id=11,
        indexer_name="DogNZB",
    )

    class _Commands:  # records follow-up enqueues; no dedup needed here
        def __init__(self):
            self.enqueued = []

        async def enqueue(self, name, payload=None, *, priority=None, triggered_by="manual"):
            self.enqueued.append(name)
            return type("_Rec", (), {"id": len(self.enqueued)})()

    def _ctx(db):
        return HandlerContext(
            db=db,
            bus=None,
            settings=Settings(config_dir="/tmp"),
            offload=daemon_offload,
            commands=_Commands(),
        )

    async def _grab_history(db):
        async with db.read_session() as session:
            rows = (await session.execute(select(GrabHistoryRow))).scalars().all()
            for r in rows:
                session.expunge(r)
            return list(rows)

    client = _CountingClient(download_id="nzo-window")
    _patch_resolution(monkeypatch, client=client)

    # Stage the crash INSIDE the write window: the first grab_history write
    # raises after download() has already returned, so the write_session rolls
    # back and nothing commits. The real write is restored for the restart.
    real_write = grab_mod.write_grab_history_rows
    state = {"n": 0}

    async def _flaky_write(*args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("simulated crash: after download(), before commit")
        return await real_write(*args, **kwargs)

    monkeypatch.setattr(grab_mod, "write_grab_history_rows", _flaky_write)

    # First process lifetime: download happens, then the crash lands before the
    # grab_history commit — so no join-key row is persisted (the real window).
    first_db = Database(db_path=db_path)
    with pytest.raises(RuntimeError):
        await _handle_grab_release(command, _ctx(first_db))
    assert client.calls == 1  # downloaded once before the crash
    assert await _grab_history(first_db) == []  # nothing committed: the window
    await first_db.engine.dispose()  # simulated kill

    # Restarted process: with no persisted row the guard cannot short-circuit,
    # so the release is downloaded AGAIN — at-least-once, the accepted duplicate
    # snatch (the safe direction vs a marker-first LOST grab).
    second_db = Database(db_path=db_path)
    try:
        await _handle_grab_release(command, _ctx(second_db))
        assert client.calls == 2  # re-downloaded after the restart
        after = await _grab_history(second_db)
        # Durable state stays single: exactly one grab_history row.
        assert len(after) == 1
        assert after[0].download_id == "nzo-window"
    finally:
        await second_db.close()


# ---------------------------------------------------------------------------
# Injection point 3 — pre-import-commit crash: re-importing an already-registered
# file after a restart is a no-op (no duplicate issue_files row).
# ---------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-007")
async def test_staged_import_crash_reimport_of_registered_file_is_noop(
    migrated_dir, tmp_path
):
    """A file registered by an earlier import run is the pre-import-commit state
    a crash leaves behind (the DB row committed; the group not yet marked done).
    After the restart, re-running the import over that same path must treat it as
    already imported and create no second ``issue_files`` row."""
    from foragerr.importer.context import ImportContext
    from foragerr.importer.pipeline import gather, import_candidate
    from foragerr.importer.sources import LibraryImportSource
    from foragerr.library import repo
    from foragerr.library.models import IssueFileRow

    db_path = migrated_dir / "foragerr.db"
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()

    # First process lifetime: seed a series+issue and register one issue-file
    # (the committed side effect of the earlier import run), then stage the crash
    # by disposing the engine before anything marks the run complete.
    first_db = Database(db_path=db_path)
    series_id, issue_id = await seed_series_issue(first_db, tmp_path)
    registered_path = str(tmp_path / "lib-root" / "Spawn" / "Spawn 001 (2024).cbz")
    async with first_db.write_session() as session:
        await repo.add_issue_file(
            session, issue_id=issue_id, path=registered_path, size=4_000_000
        )
    async with first_db.read_session() as session:
        prior = (await session.execute(select(IssueFileRow))).scalars().all()
    assert len(prior) == 1
    prior_id = prior[0].id
    await first_db.engine.dispose()  # simulated kill

    # Restarted process: re-run the import over the SAME path against a fresh
    # Database. gather skips the already-registered path, so no candidate is
    # produced and import_candidate never runs — a genuine no-op.
    second_db = Database(db_path=db_path)
    ctx = ImportContext(
        library_root=str(tmp_path / "lib-root"),
        config_dir=str(config_dir),
        reference_year=2024,
        now=dt.datetime(2026, 7, 6, 12, 0, 0),
    )
    source = LibraryImportSource(series_id=series_id, files=(registered_path,))
    try:
        async with second_db.write_session() as session:
            candidates = await gather(source, session, ctx)
            for candidate in candidates:  # empty: the registered path is skipped
                await import_candidate(session, candidate, ctx)
        assert candidates == []

        async with second_db.read_session() as session:
            rows = (await session.execute(select(IssueFileRow))).scalars().all()
        # No duplicate: exactly the one pre-crash row survives, by identity.
        assert len(rows) == 1
        assert rows[0].id == prior_id
        assert rows[0].path == registered_path
    finally:
        await second_db.close()
