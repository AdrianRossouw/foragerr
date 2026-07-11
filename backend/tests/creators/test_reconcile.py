"""Credit reconciliation, prune, and follow seeding (FRG-CRTR-002/004).

Drives a real ``refresh_series`` through the ``FakeCV`` harness so ingest,
mapping, storage, and reconciliation are exercised exactly as production runs
them, inside the single refresh write transaction.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.creators import repo as creators_repo
from foragerr.creators.models import CreatorRow, IssueCreditRow
from foragerr.library import repo
from foragerr.library.flows import refresh_series
from foragerr.library.models import IssueRow

from flows_support import FakeCV, build_factory, credit, issue


async def _make_series(
    db, root_folder_path: Path, format_profile_id: int, *, cv_volume_id: int
) -> int:
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title=f"Series {cv_volume_id}",
            start_year=2012,
            monitored=True,
            monitor_new_items="all",
            format_profile_id=format_profile_id,
            root_folder_id=(await repo.list_root_folders(session))[0].id,
            path=str(root_folder_path / f"series-{cv_volume_id}"),
        )
        return series.id


async def _run_refresh(db, settings, series_id, commands, fake):
    factory = build_factory(settings, fake.handler())
    await refresh_series(db, settings, series_id, commands=commands, factory=factory)
    return factory._transport


async def _all_creators(db) -> list[CreatorRow]:
    async with db.read_session() as session:
        return list((await session.execute(select(CreatorRow))).scalars().all())


async def _credits_for_series(db, series_id: int) -> list[IssueCreditRow]:
    async with db.read_session() as session:
        rows = (
            await session.execute(
                select(IssueCreditRow)
                .join(IssueRow, IssueRow.id == IssueCreditRow.issue_id)
                .where(IssueRow.series_id == series_id)
                .order_by(IssueCreditRow.id)
            )
        ).scalars().all()
        return list(rows)


async def _creator_by_name(db, name: str) -> CreatorRow | None:
    async with db.read_session() as session:
        return (
            await session.execute(select(CreatorRow).where(CreatorRow.name == name))
        ).scalar_one_or_none()


async def _creator_by_cv(db, cv_person_id: int) -> CreatorRow | None:
    async with db.read_session() as session:
        return await creators_repo.get_creator_by_cv(session, cv_person_id)


async def _refresh_by_cv_volume(db, settings, commands, cv_volume_id, fake):
    from foragerr.library.models import SeriesRow

    async with db.read_session() as session:
        series_id = (
            await session.execute(
                select(SeriesRow.id).where(SeriesRow.cv_volume_id == cv_volume_id)
            )
        ).scalar_one()
    await _run_refresh(db, settings, series_id, commands, fake)


# --- FRG-CRTR-001: credits ride the existing walk ---------------------------


@pytest.mark.req("FRG-CRTR-001")
async def test_credits_ride_existing_walk_no_extra_requests(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    sid_a = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    sid_b = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=2)

    with_credits = FakeCV().volume(1).issues(
        1,
        [
            issue(100, "1", credits=[credit(10, "Alice", "writer, penciler")]),
            issue(101, "2", credits=[credit(11, "Bob", "artist")]),
        ],
    )
    without = FakeCV().volume(2).issues(2, [issue(200, "1"), issue(201, "2")])

    t_with = await _run_refresh(db, settings, sid_a, commands, with_credits)
    t_without = await _run_refresh(db, settings, sid_b, commands, without)

    def issues_reqs(t):
        return [r for r in t.requests if r.url.path.endswith("/issues/")]

    # Same number of ComicVine requests with and without credits, and NOT a
    # single per-issue detail fetch (singular ``/issue/4050-`` endpoint).
    assert len(issues_reqs(t_with)) == len(issues_reqs(t_without))
    assert [r for r in t_with.requests if "/issue/4050-" in r.url.path] == []
    # ...and the batch walk actually requested the field.
    assert "person_credits" in issues_reqs(t_with)[0].url.params.get("field_list")


# --- FRG-CRTR-002: storage + idempotent reconciliation ----------------------


@pytest.mark.req("FRG-CRTR-002")
async def test_reconcile_creates_creators_and_credits(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    fake = FakeCV().volume(1).issues(
        1,
        [
            issue(100, "1", credits=[credit(10, "Alice", "writer")]),
            issue(101, "2", credits=[credit(10, "Alice", "writer"), credit(11, "Bob", "artist")]),
        ],
    )
    await _run_refresh(db, settings, sid, commands, fake)

    names = {c.name for c in await _all_creators(db)}
    assert names == {"Alice", "Bob"}
    # Alice writer on both issues (2 rows) + Bob artist on one (1 row).
    assert len(await _credits_for_series(db, sid)) == 3
    # Single-series creators are not seeded followed.
    assert (await _creator_by_name(db, "Alice")).followed is False


@pytest.mark.req("FRG-CRTR-002")
async def test_repeat_refresh_is_a_no_op(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    fake = FakeCV().volume(1).issues(
        1, [issue(100, "1", credits=[credit(10, "Alice", "writer, penciler")])]
    )
    await _run_refresh(db, settings, sid, commands, fake)
    first = {c.id for c in await _credits_for_series(db, sid)}
    creators_first = {c.id for c in await _all_creators(db)}

    # Identical CV data on the second run must change no rows.
    await _run_refresh(db, settings, sid, commands, fake)
    assert {c.id for c in await _credits_for_series(db, sid)} == first
    assert {c.id for c in await _all_creators(db)} == creators_first


@pytest.mark.req("FRG-CRTR-002")
async def test_dropped_credit_is_removed(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    fake = FakeCV().volume(1).issues(
        1, [issue(100, "1", credits=[credit(10, "Alice", "writer, penciler")])]
    )
    await _run_refresh(db, settings, sid, commands, fake)
    assert {c.role_normalized for c in await _credits_for_series(db, sid)} == {
        "writer",
        "penciler",
    }

    # CV drops the penciler role -> exactly that association is removed.
    fake.issues(1, [issue(100, "1", credits=[credit(10, "Alice", "writer")])])
    await _run_refresh(db, settings, sid, commands, fake)
    assert {c.role_normalized for c in await _credits_for_series(db, sid)} == {"writer"}


@pytest.mark.req("FRG-CRTR-002")
async def test_partial_fetch_never_deletes_credits(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    from flows_support import flows_settings

    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    # First, a complete refresh giving both issues their credits.
    fake = FakeCV().volume(1).issues(
        1,
        [
            issue(100, "1", credits=[credit(10, "Alice", "writer")]),
            issue(101, "2", credits=[credit(11, "Bob", "artist")]),
        ],
    )
    await _run_refresh(db, settings, sid, commands, fake)
    assert len(await _credits_for_series(db, sid)) == 2

    # Now a PARTIAL refresh (page size 1, fails after the first page) so issue
    # 101 is absent from the fetch — its credit must survive untouched.
    small = flows_settings(settings.config_dir, comicvine_page_size=1)
    partial = FakeCV().volume(1).issues(
        1,
        [
            issue(100, "1", credits=[credit(10, "Alice", "writer")]),
            issue(101, "2", credits=[credit(11, "Bob", "artist")]),
        ],
        fail_after_offset=1,
    )
    await _run_refresh(db, small, sid, commands, partial)
    roles = {c.role_normalized for c in await _credits_for_series(db, sid)}
    assert roles == {"writer", "artist"}  # Bob's credit on issue 101 intact


@pytest.mark.req("FRG-CRTR-002")
async def test_issue_delete_cascades_credits_and_prunes_orphan_creator(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    fake = FakeCV().volume(1).issues(
        1,
        [
            issue(100, "1", credits=[credit(10, "Alice", "writer")]),
            issue(101, "2", credits=[credit(11, "Bob", "artist")]),
        ],
    )
    await _run_refresh(db, settings, sid, commands, fake)
    assert {c.name for c in await _all_creators(db)} == {"Alice", "Bob"}

    # Complete refresh with issue 101 gone -> the issue is deleted, its credit
    # cascades, and Bob (now creditless, never touched, unfollowed) is pruned.
    fake.issues(1, [issue(100, "1", credits=[credit(10, "Alice", "writer")])])
    await _run_refresh(db, settings, sid, commands, fake)
    assert {c.name for c in await _all_creators(db)} == {"Alice"}
    assert {c.role_normalized for c in await _credits_for_series(db, sid)} == {"writer"}


# --- FRG-CRTR-004: follow flag + threshold seeding --------------------------


async def _seed_two_series_creator(
    db, settings, commands, root_folder_path, format_profile_id
) -> int:
    """Refresh two series both crediting Alice; return her creator id."""
    s1 = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    s2 = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=2)
    f1 = FakeCV().volume(1).issues(
        1,
        [
            issue(100, "1", credits=[credit(10, "Alice", "writer")]),
            issue(101, "2", credits=[credit(20, "Carol", "letterer")]),
        ],
    )
    f2 = FakeCV().volume(2).issues(
        2, [issue(200, "1", credits=[credit(10, "Alice", "artist")])]
    )
    await _run_refresh(db, settings, s1, commands, f1)
    await _run_refresh(db, settings, s2, commands, f2)
    return (await _creator_by_name(db, "Alice")).id


@pytest.mark.req("FRG-CRTR-004")
async def test_threshold_seeding_two_series_follows_one_series_does_not(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    await _seed_two_series_creator(
        db, settings, commands, root_folder_path, format_profile_id
    )
    alice = await _creator_by_name(db, "Alice")
    carol = await _creator_by_name(db, "Carol")
    # Alice spans two series -> seeded followed; follow_touched stays NULL.
    assert alice.followed is True
    assert alice.follow_touched is None
    assert alice.followed_at is not None
    # Carol is in one series only -> stays unfollowed.
    assert carol.followed is False


@pytest.mark.req("FRG-CRTR-004")
async def test_user_unfollow_is_never_overwritten_by_refresh(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    alice_id = await _seed_two_series_creator(
        db, settings, commands, root_folder_path, format_profile_id
    )
    # User unfollows the seeded creator -> follow_touched set.
    async with db.write_session() as session:
        await creators_repo.set_creator_followed(session, alice_id, False)

    # Re-refresh both series (Alice still spans two series) -> seeding must NOT
    # re-follow her, because the flag is now user-owned.
    f1 = FakeCV().volume(1).issues(
        1, [issue(100, "1", credits=[credit(10, "Alice", "writer")])]
    )
    f2 = FakeCV().volume(2).issues(
        2, [issue(200, "1", credits=[credit(10, "Alice", "artist")])]
    )
    await _refresh_by_cv_volume(db, settings, commands, 1, f1)
    await _refresh_by_cv_volume(db, settings, commands, 2, f2)

    alice = await _creator_by_cv(db, 10)
    assert alice.followed is False
    assert alice.follow_touched is not None


@pytest.mark.req("FRG-CRTR-004")
async def test_touched_creditless_creator_survives_and_is_not_reseeded(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    alice_id = await _seed_two_series_creator(
        db, settings, commands, root_folder_path, format_profile_id
    )
    async with db.write_session() as session:
        await creators_repo.set_creator_followed(session, alice_id, False)

    # Drop Alice from both series entirely -> she becomes creditless but, being
    # user-touched, must NOT be pruned (pruning would erase the unfollow memory).
    empty1 = FakeCV().volume(1).issues(
        1,
        [
            issue(100, "1", credits=[]),
            issue(101, "2", credits=[credit(20, "Carol", "letterer")]),
        ],
    )
    empty2 = FakeCV().volume(2).issues(2, [issue(200, "1", credits=[])])
    await _refresh_by_cv_volume(db, settings, commands, 1, empty1)
    await _refresh_by_cv_volume(db, settings, commands, 2, empty2)

    alice = await _creator_by_cv(db, 10)
    assert alice is not None  # survived the creditless period
    assert alice.followed is False

    # Re-ingest Alice into both series again -> because follow_touched is set,
    # threshold seeding must NOT re-follow the deliberately-unfollowed creator.
    f1 = FakeCV().volume(1).issues(
        1, [issue(100, "1", credits=[credit(10, "Alice", "writer")])]
    )
    f2 = FakeCV().volume(2).issues(
        2, [issue(200, "1", credits=[credit(10, "Alice", "artist")])]
    )
    await _refresh_by_cv_volume(db, settings, commands, 1, f1)
    await _refresh_by_cv_volume(db, settings, commands, 2, f2)

    alice = await _creator_by_cv(db, 10)
    assert alice.followed is False  # never re-seeded
