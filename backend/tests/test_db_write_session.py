"""Single-writer discipline and transactional atomicity (FRG-DB-006/007)."""

from __future__ import annotations

import asyncio
import sqlite3
import threading

import pytest
from sqlalchemy import func, select

from foragerr.db import (
    CommandRow,
    Database,
    DatabaseBusyError,
    JobHistoryRow,
    queue_event,
    utcnow,
)


def _command_row(**overrides) -> CommandRow:
    defaults = dict(
        name="noop",
        status="queued",
        payload="{}",
        payload_hash="h",
        queued_at=utcnow(),
    )
    defaults.update(overrides)
    return CommandRow(**defaults)


async def _count(db: Database, model=CommandRow) -> int:
    async with db.read_session() as session:
        return (await session.execute(select(func.count(model.id)))).scalar()


@pytest.mark.req("FRG-DB-006")
async def test_concurrent_writers_serialized_with_zero_locked_errors(db):
    tasks_n, writes_per_task = 25, 4

    async def writer(task_id: int) -> None:
        for i in range(writes_per_task):
            async with db.write_session() as session:
                session.add(_command_row(payload_hash=f"t{task_id}-w{i}"))
                await asyncio.sleep(0)  # force interleaving between writers

    results = await asyncio.gather(
        *(writer(t) for t in range(tasks_n)), return_exceptions=True
    )

    errors = [r for r in results if isinstance(r, BaseException)]
    assert errors == []  # zero unhandled locked (or any) errors
    assert await _count(db) == tasks_n * writes_per_task  # nothing lost


@pytest.mark.req("FRG-DB-006")
async def test_write_windows_do_not_overlap(db):
    windows: list[str] = []

    async def writer(tag: str) -> None:
        async with db.write_session() as session:
            windows.append(f"start:{tag}")
            session.add(_command_row(payload_hash=tag))
            await asyncio.sleep(0.05)  # widen the window
            windows.append(f"end:{tag}")

    await asyncio.gather(writer("one"), writer("two"))

    assert len(windows) == 4
    first, second = windows[0].split(":")[1], windows[2].split(":")[1]
    assert windows == [f"start:{first}", f"end:{first}", f"start:{second}", f"end:{second}"]


@pytest.mark.req("FRG-DB-006")
async def test_induced_busy_is_retried_until_success(migrated_dir):
    db_path = migrated_dir / "foragerr.db"
    db = Database(db_path=db_path, busy_timeout_ms=5000)
    try:
        external = sqlite3.connect(db_path, check_same_thread=False)
        external.execute("BEGIN IMMEDIATE")  # holds the write lock
        external.execute(
            "INSERT INTO commands(name,status,payload,payload_hash,queued_at)"
            " VALUES ('ext','queued','{}','ext','2026-01-01')"
        )

        def release_soon() -> None:
            import time

            time.sleep(0.3)
            external.commit()
            external.close()

        threading.Thread(target=release_soon).start()

        async with db.write_session() as session:  # must NOT raise
            session.add(_command_row(payload_hash="ours"))

        assert await _count(db) == 2  # both the external and our write landed
    finally:
        await db.close()


@pytest.mark.req("FRG-DB-006")
async def test_lock_held_beyond_budget_raises_distinct_error(migrated_dir):
    db_path = migrated_dir / "foragerr.db"
    db = Database(
        db_path=db_path,
        busy_timeout_ms=100,
        commit_retry_attempts=2,
        commit_retry_base_delay=0.01,
    )
    external = sqlite3.connect(db_path)
    external.execute("BEGIN IMMEDIATE")  # never released during the attempt
    try:
        with pytest.raises(DatabaseBusyError):  # distinct typed timeout error,
            async with db.write_session() as session:  # never a raw locked error
                session.add(_command_row(payload_hash="blocked"))
    finally:
        external.rollback()
        external.close()
        await db.close()


@pytest.mark.req("FRG-DB-007")
async def test_exception_inside_write_session_rolls_back_everything(db):
    with pytest.raises(ValueError, match="midway"):
        async with db.write_session() as session:
            session.add(_command_row(payload_hash="one"))
            await session.flush()
            session.add(_command_row(payload_hash="two"))
            raise ValueError("midway")

    assert await _count(db) == 0  # nothing visible to subsequent readers


@pytest.mark.req("FRG-DB-007")
async def test_interrupted_multistep_operation_leaves_no_partial_rows(db):
    """Series-add analogue: parent row + child rows in ONE write_session."""

    async def add_with_children(fail_after: int | None) -> None:
        async with db.write_session() as session:
            parent = _command_row(payload_hash="series-add")
            session.add(parent)
            await session.flush()
            for index in range(4):
                if fail_after is not None and index == fail_after:
                    raise RuntimeError("killed partway through")
                session.add(
                    JobHistoryRow(
                        command_id=parent.id,
                        name=f"issue-{index}",
                        triggered_by="manual",
                        outcome="completed",
                    )
                )

    with pytest.raises(RuntimeError):
        await add_with_children(fail_after=2)
    assert await _count(db, CommandRow) == 0  # no partial parent
    assert await _count(db, JobHistoryRow) == 0  # no partial children

    await add_with_children(fail_after=None)
    assert await _count(db, CommandRow) == 1  # complete, or nothing
    assert await _count(db, JobHistoryRow) == 4


@pytest.mark.req("FRG-DB-007")
async def test_events_publish_only_after_commit(db):
    published: list[str] = []
    db.event_publisher = published.append

    async with db.write_session() as session:
        session.add(_command_row(payload_hash="evt"))
        queue_event(session, "series-added")
        assert published == []  # not yet — commit hasn't happened
    assert published == ["series-added"]  # delivered strictly after commit


@pytest.mark.req("FRG-DB-007")
async def test_rolled_back_transaction_publishes_no_events(db):
    published: list[str] = []
    db.event_publisher = published.append

    with pytest.raises(RuntimeError):
        async with db.write_session() as session:
            session.add(_command_row(payload_hash="evt"))
            queue_event(session, "should-never-appear")
            raise RuntimeError("abort")

    assert published == []
    assert await _count(db) == 0
