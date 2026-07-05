"""Refresh reconciliation, monitoring strategies, policy, covers, and chain.

FRG-META-008 (reconcile insert/update/delete keyed by cv_issue_id, one
transaction, post-commit event, partial-fetch guard, never-delete-with-files),
FRG-SER-006 (six add-time strategies, applied once then cleared), FRG-SER-007
(monitor-new-items policy on refresh inserts), FRG-SER-005 (chained commands,
restart-safe), FRG-META-013 (re-fetch cover only on URL change).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import func, select

from conftest import eventually
from foragerr.commands import CommandService
from foragerr.db import CommandRow, JobHistoryRow
from foragerr.events import EventBus
from foragerr.library import repo
from foragerr.library.flows import (
    SeriesRefreshed,
    add_series,
    encode_add_options,
    refresh_series,
)
from foragerr.library.flows import refresh as refresh_mod
from foragerr.library.models import IssueRow, SeriesRow

from flows_support import FakeCV, build_factory, flows_settings, issue


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


@pytest.fixture
async def commands(db, settings, command_registry):
    return CommandService(db, settings)


async def _make_series(
    db,
    root_folder_path: Path,
    format_profile_id: int,
    *,
    cv_volume_id: int = 1,
    monitor_new_items: str = "all",
    add_options: str | None = None,
    monitored: bool = True,
) -> int:
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title="Saga",
            start_year=2012,
            monitored=monitored,
            monitor_new_items=monitor_new_items,
            format_profile_id=format_profile_id,
            root_folder_id=(await repo.list_root_folders(session))[0].id,
            path=str(root_folder_path / f"series-{cv_volume_id}"),
            add_options=add_options,
        )
        return series.id


async def _issues(db, series_id: int) -> list[IssueRow]:
    async with db.read_session() as session:
        return await repo.list_issues_for_series(session, series_id)


# --- reconciliation (FRG-META-008) ------------------------------------------


@pytest.mark.req("FRG-META-008")
async def test_reconcile_insert_update_delete_one_txn_and_event(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    series_id = await _make_series(db, root_folder_path, format_profile_id)
    async with db.write_session() as session:
        await repo.create_issue(session, series_id=series_id, cv_issue_id=100, issue_number="1")
        await repo.create_issue(
            session, series_id=series_id, cv_issue_id=101, issue_number="2", title="Old"
        )
        await repo.create_issue(session, series_id=series_id, cv_issue_id=102, issue_number="3")

    bus = EventBus()
    received: list[SeriesRefreshed] = []
    bus.subscribe(SeriesRefreshed, received.append)
    db.event_publisher = bus.publish

    fake = (
        FakeCV()
        .volume(1)
        .issues(
            1,
            [
                issue(100, "1"),
                issue(101, "2", title="New"),  # changed title
                issue(103, "4"),  # inserted
                # cv 102 absent -> deleted
            ],
        )
    )
    factory = build_factory(settings, fake.handler())
    summary = await refresh_series(db, settings, series_id, commands=commands, factory=factory)
    # exactly: one insert (103), one update (101), one delete (102)
    assert summary == "inserted=1 updated=1 deleted=1 partial=False"

    rows = await _issues(db, series_id)
    by_cv = {r.cv_issue_id: r for r in rows}
    assert set(by_cv) == {100, 101, 103}
    assert by_cv[101].title == "New"
    assert received == [SeriesRefreshed(series_id, partial=False)]


@pytest.mark.req("FRG-META-008")
async def test_partial_fetch_skips_delete_arm(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    series_id = await _make_series(db, root_folder_path, format_profile_id)
    async with db.write_session() as session:
        for cv, num in [(100, "1"), (101, "2"), (102, "3")]:
            await repo.create_issue(session, series_id=series_id, cv_issue_id=cv, issue_number=num)

    # page size 1, fail the walk after the first page -> complete=False
    small = flows_settings(settings.config_dir, comicvine_page_size=1)
    fake = FakeCV().volume(1).issues(
        1, [issue(100, "1"), issue(101, "2"), issue(102, "3")], fail_after_offset=1
    )
    factory = build_factory(small, fake.handler())
    summary = await refresh_series(db, small, series_id, commands=commands, factory=factory)
    assert summary.endswith("partial=True")
    assert "deleted=0" in summary

    rows = await _issues(db, series_id)
    assert {r.cv_issue_id for r in rows} == {100, 101, 102}  # nothing deleted


@pytest.mark.req("FRG-META-008")
async def test_issue_with_file_is_never_hard_deleted(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    series_id = await _make_series(db, root_folder_path, format_profile_id)
    async with db.write_session() as session:
        keep = await repo.create_issue(session, series_id=series_id, cv_issue_id=100, issue_number="1")
        orphan = await repo.create_issue(session, series_id=series_id, cv_issue_id=102, issue_number="3")
        await repo.add_issue_file(session, issue_id=orphan.id, path="/tmp/x.cbz", size=10)

    fake = FakeCV().volume(1).issues(1, [issue(100, "1")])  # 102 absent, complete
    factory = build_factory(settings, fake.handler())
    summary = await refresh_series(db, settings, series_id, commands=commands, factory=factory)
    assert "deleted=0" in summary and summary.endswith("partial=False")

    rows = await _issues(db, series_id)
    assert {r.cv_issue_id for r in rows} == {100, 102}  # 102 kept (has a file)


# --- monitor-new-items policy (FRG-SER-007) ---------------------------------


@pytest.mark.req("FRG-SER-007")
@pytest.mark.parametrize("policy,expected", [("all", True), ("none", False)])
async def test_new_issue_monitored_per_policy(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id, policy, expected
):
    series_id = await _make_series(
        db, root_folder_path, format_profile_id, monitor_new_items=policy
    )
    fake = FakeCV().volume(1).issues(1, [issue(100, "1")])
    factory = build_factory(settings, fake.handler())
    await refresh_series(db, settings, series_id, commands=commands, factory=factory)

    rows = await _issues(db, series_id)
    assert rows[0].monitored is expected


# --- add-time monitoring strategies (FRG-SER-006) ---------------------------


@pytest.mark.req("FRG-SER-006")
@pytest.mark.parametrize(
    "strategy,expected_cv",
    [
        ("all", {1, 2, 3}),
        ("none", set()),
        ("first", {1}),
        ("existing", {1}),  # only the issue with a file
        ("missing", {2, 3}),  # only the file-less issues
        ("future", {2}),  # only the future-dated issue
    ],
)
async def test_each_monitor_strategy(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id,
    strategy, expected_cv,
):
    add_options = encode_add_options(
        monitor_strategy=strategy, monitor_new_items="all", search_on_add=False
    )
    series_id = await _make_series(
        db, root_folder_path, format_profile_id, add_options=add_options
    )
    # Pre-create the three issues so file/date state is under test control;
    # the refresh returns the same three (matched, no insert/delete).
    async with db.write_session() as session:
        i1 = await repo.create_issue(
            session, series_id=series_id, cv_issue_id=1, issue_number="1",
            cover_date=dt.date(2001, 1, 1),
        )
        await repo.create_issue(
            session, series_id=series_id, cv_issue_id=2, issue_number="2",
            cover_date=dt.date(2999, 1, 1),  # future
        )
        await repo.create_issue(
            session, series_id=series_id, cv_issue_id=3, issue_number="3",
            cover_date=dt.date(2001, 1, 1),
        )
        await repo.add_issue_file(session, issue_id=i1.id, path="/tmp/i1.cbz", size=5)

    fake = FakeCV().volume(1).issues(
        1,
        [
            issue(1, "1", cover_date="2001-01-01"),
            issue(2, "2", cover_date="2999-01-01"),
            issue(3, "3", cover_date="2001-01-01"),
        ],
    )
    factory = build_factory(settings, fake.handler())
    await refresh_series(db, settings, series_id, commands=commands, factory=factory)

    rows = await _issues(db, series_id)
    monitored_cv = {r.cv_issue_id for r in rows if r.monitored}
    assert monitored_cv == expected_cv

    # add_options cleared exactly once
    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
    assert series.add_options is None


@pytest.mark.req("FRG-SER-006")
async def test_strategy_applied_once_then_cleared(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    fake = FakeCV().volume(5, name="Saga").issues(5, [issue(200, "1"), issue(201, "2")])
    factory = build_factory(settings, fake.handler())
    result = await add_series(
        db, settings, cv_volume_id=5, root_folder_id=root_folder_id,
        commands=commands, monitor_strategy="none", monitor_new_items="all",
        factory=factory,
    )
    series_id = result.series.id

    await refresh_series(db, settings, series_id, commands=commands, factory=factory)
    rows = await _issues(db, series_id)
    assert all(r.monitored is False for r in rows)  # strategy "none" applied

    # A user re-monitors one issue by hand.
    async with db.write_session() as session:
        await repo.set_issue_monitored(session, rows[0].id, True)

    # A second refresh discovers a new issue; the add-time strategy must NOT
    # re-apply (the hand-monitored issue stays True), and the new issue is
    # governed by the monitor-new-items policy (all -> monitored).
    fake.issues(5, [issue(200, "1"), issue(201, "2"), issue(202, "3")])
    await refresh_series(db, settings, series_id, commands=commands, factory=factory)

    rows = await _issues(db, series_id)
    by_cv = {r.cv_issue_id: r for r in rows}
    assert by_cv[200].monitored is True  # strategy did not re-force False
    assert by_cv[202].monitored is True  # new issue via policy "all"


# --- cover cache (FRG-META-013) ---------------------------------------------


@pytest.mark.req("FRG-META-013")
async def test_cover_refetched_only_when_url_changes(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    img1 = "https://comicvine.gamespot.com/a/uploads/original/cover1.jpg"
    img2 = "https://comicvine.gamespot.com/a/uploads/original/cover2.jpg"
    series_id = await _make_series(db, root_folder_path, format_profile_id)

    fake = FakeCV().volume(1, image_url=img1).issues(1, [issue(100, "1")])
    factory = build_factory(settings, fake.handler())
    transport = factory._transport  # the shared RecordingTransport

    def image_hits() -> int:
        return sum(1 for r in transport.requests if r.url.path.endswith(".jpg"))

    await refresh_series(db, settings, series_id, commands=commands, factory=factory)
    cover_file = Path(settings.config_dir) / "covers" / f"{series_id}.jpg"
    assert cover_file.exists()
    assert image_hits() == 1

    # Same URL -> reuse, no new image request.
    await refresh_series(db, settings, series_id, commands=commands, factory=factory)
    assert image_hits() == 1

    # Changed URL -> re-fetch.
    fake.volume(1, image_url=img2).issues(1, [issue(100, "1")])
    await refresh_series(db, settings, series_id, commands=commands, factory=factory)
    assert image_hits() == 2


# --- chained commands + restart-safety (FRG-SER-005) ------------------------


@pytest.mark.req("FRG-SER-005")
async def test_full_chain_runs_via_command_backbone(
    db, settings, monkeypatch, root_folder_id, root_folder_path, format_profile_id,
    command_registry,
):
    fake = FakeCV().volume(8, name="Bone").issues(8, [issue(300, "1"), issue(301, "2")])
    monkeypatch.setattr(
        refresh_mod, "comicvine_factory",
        lambda s: build_factory(s, fake.handler()),
    )
    service = CommandService(db, settings, poll_interval=0.02)

    result = await add_series(
        db, settings, cv_volume_id=8, root_folder_id=root_folder_id,
        commands=service, monitor_strategy="all", search_on_add=True,
        factory=build_factory(settings, fake.handler()),
    )
    series_id = result.series.id

    await service.start()
    try:
        # The refresh command runs to completion...
        async def _refresh_done():
            rec = await service.get(result.refresh_command_id)
            return rec if rec and rec.status == "completed" else None

        await eventually(_refresh_done)

        # ...issues were reconciled and add_options cleared...
        async def _issues_present():
            rows = await _issues(db, series_id)
            return len(rows) == 2

        await eventually(_issues_present)
        async with db.read_session() as session:
            series = await repo.get_series(session, series_id)
        assert series.add_options is None

        # ...and scan + search commands appeared on the backbone.
        async def _chain_enqueued():
            async with db.read_session() as session:
                names = set(
                    (await session.execute(select(CommandRow.name))).scalars().all()
                )
            return {"scan-series", "series-search"} <= names

        await eventually(_chain_enqueued)
    finally:
        await service.drain(1.0)


@pytest.mark.req("FRG-SER-005")
async def test_interrupted_refresh_resumes_from_persisted_queue(
    db, settings, monkeypatch, root_folder_id, root_folder_path, format_profile_id,
    command_registry,
):
    fake = FakeCV().volume(9, name="ODY-C").issues(9, [issue(400, "1")])
    monkeypatch.setattr(
        refresh_mod, "comicvine_factory",
        lambda s: build_factory(s, fake.handler()),
    )
    # Enqueue the refresh, then simulate a kill mid-flight (row stuck 'started').
    enqueuer = CommandService(db, settings)
    result = await add_series(
        db, settings, cv_volume_id=9, root_folder_id=root_folder_id,
        commands=enqueuer, monitor_strategy="all",
        factory=build_factory(settings, fake.handler()),
    )
    async with db.write_session() as session:
        row = await session.get(CommandRow, result.refresh_command_id)
        row.status = "started"
        row.started_at = row.queued_at

    # New process: orphan recovery re-queues and the chain completes.
    service = CommandService(db, settings, poll_interval=0.02)
    await service.start()
    try:
        async def _done():
            rec = await service.get(result.refresh_command_id)
            return rec if rec and rec.status == "completed" else None

        await eventually(_done)
        rows = await _issues(db, result.series.id)
        assert {r.cv_issue_id for r in rows} == {400}
        async with db.read_session() as session:
            series = await repo.get_series(session, result.series.id)
        assert series.add_options is None  # strategy applied exactly once
    finally:
        await service.drain(1.0)
