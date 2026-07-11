"""Credit reconciliation, prune, and explicit-only follows (FRG-CRTR-002/004).

Drives a real ``refresh_series`` through the ``FakeCV`` harness so ingest,
mapping, storage, and reconciliation are exercised exactly as production runs
them, inside the single refresh write transaction. Reconciliation NEVER derives
a follow (owner decision 2026-07-11); ``followed`` only ever changes through the
explicit follow API.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.creators import repo as creators_repo
from foragerr.creators.models import CreatorRow, IssueCreditRow
from foragerr.creators.reconcile import reconcile_issue_credits
from foragerr.library import repo
from foragerr.library.flows import refresh_series
from foragerr.library.models import IssueRow
from foragerr.metadata.models import CreditRecord

from flows_support import FakeCV, build_factory, credit, flows_settings, issue


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


def _detail_reqs(transport) -> list:
    """Per-issue credit detail requests (``issue/4050-{id}/``) on a transport."""
    return [r for r in transport.requests if "/issue/4050-" in r.url.path]


def _detail_ids(transport) -> list[int]:
    """The issue ids fetched via the detail endpoint, in request order."""
    return [
        int(r.url.path.split("4050-")[1].rstrip("/")) for r in _detail_reqs(transport)
    ]


async def _stamped_cv_ids(db, series_id: int) -> set[int]:
    async with db.read_session() as session:
        rows = await session.execute(
            select(IssueRow.cv_issue_id).where(
                IssueRow.series_id == series_id,
                IssueRow.credits_fetched_at.is_not(None),
            )
        )
        return set(rows.scalars().all())


# --- FRG-CRTR-001: credits come from bounded, rate-gated detail fetches -------


@pytest.mark.req("FRG-CRTR-001")
async def test_credits_come_from_per_issue_detail_fetches(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """Credits are sourced from the DETAIL endpoint (the list returns null on
    the real API): one ``issue/4050-{id}/`` fetch per credit-needing issue,
    each through the shared rate gate (all client calls are gated)."""
    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    fake = FakeCV().volume(1).issues(
        1,
        [
            issue(100, "1", credits=[credit(10, "Alice", "writer, penciler")]),
            issue(101, "2", credits=[credit(11, "Bob", "artist")]),
        ],
    )
    transport = await _run_refresh(db, settings, sid, commands, fake)

    # One detail fetch per issue — that is the credit source now.
    assert sorted(_detail_ids(transport)) == [100, 101]
    names = {c.name for c in await _all_creators(db)}
    assert names == {"Alice", "Bob"}
    # Both issues are now stamped, so a repeat refresh issues NO detail fetches.
    assert await _stamped_cv_ids(db, sid) == {100, 101}
    transport2 = await _run_refresh(
        db, settings, sid, commands, FakeCV().volume(1).issues(
            1,
            [
                issue(100, "1", credits=[credit(10, "Alice", "writer, penciler")]),
                issue(101, "2", credits=[credit(11, "Bob", "artist")]),
            ],
        ),
    )
    assert _detail_ids(transport2) == []


@pytest.mark.req("FRG-CRTR-001")
async def test_detail_fetches_are_bounded_newest_first(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """With more credit-needing issues than the per-run bound, exactly the
    bound's worth of detail fetches go out, targeting the NEWEST issues first
    (store_date DESC, then cover_date, then id); the tail is left for later."""
    bounded = flows_settings(settings.config_dir, credits_fetch_per_refresh=2)
    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    fake = FakeCV().volume(1).issues(
        1,
        [
            issue(100, "1", store_date="2012-01-01",
                  credits=[credit(10, "A", "writer")]),
            issue(101, "2", store_date="2012-06-01",
                  credits=[credit(11, "B", "writer")]),
            issue(102, "3", store_date="2012-09-01",
                  credits=[credit(12, "C", "writer")]),
        ],
    )
    transport = await _run_refresh(db, bounded, sid, commands, fake)

    # Exactly the bound; the two NEWEST (102 = Sep, 101 = Jun) fetched first.
    assert _detail_ids(transport) == [102, 101]
    assert await _stamped_cv_ids(db, sid) == {101, 102}
    assert {c.name for c in await _all_creators(db)} == {"B", "C"}

    # A second run fetches the remaining tail (100) and nothing past the bound.
    transport2 = await _run_refresh(db, bounded, sid, commands, fake)
    assert _detail_ids(transport2) == [100]
    assert await _stamped_cv_ids(db, sid) == {100, 101, 102}
    assert {c.name for c in await _all_creators(db)} == {"A", "B", "C"}


@pytest.mark.req("FRG-CRTR-001")
async def test_zero_credit_issue_is_stamped_and_not_refetched(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """A detail fetch that returns no credits still stamps the issue (no rows
    written) so subsequent refreshes never re-fetch it (design decision 6)."""
    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    fake = FakeCV().volume(1).issues(1, [issue(100, "1", credits=[])])
    transport = await _run_refresh(db, settings, sid, commands, fake)

    assert _detail_ids(transport) == [100]  # fetched once
    assert await _credits_for_series(db, sid) == []  # no credit rows
    assert await _stamped_cv_ids(db, sid) == {100}  # but stamped

    transport2 = await _run_refresh(db, settings, sid, commands, fake)
    assert _detail_ids(transport2) == []  # never re-fetched


@pytest.mark.req("FRG-CRTR-001")
async def test_failed_detail_fetch_is_unstamped_and_retried_next_run(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """A failed detail fetch (5xx) leaves the issue unstamped and does not fail
    the refresh; the next run retries it and lands the credit."""
    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    # Issue 100 succeeds, issue 101's detail fetch 500s this run.
    failing = FakeCV().volume(1).issues(
        1,
        [
            issue(100, "1", credits=[credit(10, "Alice", "writer")]),
            issue(101, "2", credits=[credit(11, "Bob", "artist")]),
        ],
        detail_fail={101: 500},
    )
    # Refresh completes normally (returns a summary, does not raise).
    result = await refresh_series(
        db, settings, sid, commands=commands,
        factory=build_factory(settings, failing.handler()),
    )
    assert "inserted=" in result
    assert await _stamped_cv_ids(db, sid) == {100}  # only the success stamped
    assert {c.name for c in await _all_creators(db)} == {"Alice"}

    # Next run: 101 is still credit-needing and now its detail fetch succeeds.
    healthy = FakeCV().volume(1).issues(
        1,
        [
            issue(100, "1", credits=[credit(10, "Alice", "writer")]),
            issue(101, "2", credits=[credit(11, "Bob", "artist")]),
        ],
    )
    transport = await _run_refresh(db, settings, sid, commands, healthy)
    assert _detail_ids(transport) == [101]  # only the previously-failed issue
    assert {c.name for c in await _all_creators(db)} == {"Alice", "Bob"}


# --- Anti-masking tripwire (design decision 5) ------------------------------


@pytest.mark.req("FRG-CRTR-001")
async def test_tripwire_list_null_detail_full_is_the_canonical_shape(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """Canonical fixture shape: the LIST rows carry NO credits (mirroring the
    real API's null), the DETAIL endpoint supplies them, and end-to-end ingest
    lands the credit via the detail path. Fails if the fixture regresses to
    serving list credits as the ingest source (the v0.5.0 masking bug)."""
    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    fake = FakeCV().volume(1).issues(
        1, [issue(100, "1", credits=[credit(10, "Alice", "writer")])]
    )
    # Fixture invariant: the credit is NOT on the list row (default routing),
    # only on the detail endpoint — this is what pins list-null/detail-full.
    assert "person_credits" not in fake._issues[1][0]
    assert 100 in fake._issue_credits

    transport = await _run_refresh(db, settings, sid, commands, fake)

    # The list walk requested person_credits but the rows carried none...
    list_reqs = [r for r in transport.requests if r.url.path.endswith("/issues/")]
    assert list_reqs and "person_credits" in list_reqs[0].url.params.get("field_list")
    # ...and the credit was sourced through the detail endpoint end-to-end.
    assert _detail_ids(transport) == [100]
    assert {c.name for c in await _all_creators(db)} == {"Alice"}


@pytest.mark.req("FRG-CRTR-001")
async def test_tripwire_opportunistic_list_credits_still_map(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """Opportunistic path kept: a list row carrying credits for an issue the run
    does NOT detail-fetch (here, beyond the per-run bound) still maps at zero
    extra cost. Guards against silently dropping list-supplied credits should CV
    ever serve them."""
    bounded = flows_settings(settings.config_dir, credits_fetch_per_refresh=1)
    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    # ``list_credits=True`` also serves credits on the list rows. With bound=1
    # only the NEWEST issue (200) is detail-fetched; issue 100 is beyond the
    # bound, so its LIST credit is the only possible source this run.
    fake = FakeCV().volume(1).issues(
        1,
        [
            issue(100, "1", store_date="2012-01-01",
                  credits=[credit(10, "Alice", "writer")]),
            issue(200, "2", store_date="2012-09-01",
                  credits=[credit(11, "Bob", "writer")]),
        ],
        list_credits=True,
    )
    transport = await _run_refresh(db, bounded, sid, commands, fake)

    # Only the newest issue is detail-fetched (bound=1)...
    assert _detail_ids(transport) == [200]
    # ...yet Alice (issue 100, beyond the bound) lands via the list mapping.
    assert {c.name for c in await _all_creators(db)} == {"Alice", "Bob"}


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
    # Reconciliation never derives a follow: a freshly ingested creator is
    # unfollowed until an explicit API toggle.
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


async def _issue_id_for_cv(db, series_id: int, cv_issue_id: int) -> int:
    async with db.read_session() as session:
        return (
            await session.execute(
                select(IssueRow.id).where(
                    IssueRow.series_id == series_id,
                    IssueRow.cv_issue_id == cv_issue_id,
                )
            )
        ).scalar_one()


async def _persist_zero_credit_issue(
    db, settings, commands, root_folder_path, format_profile_id, *, cv_issue_id=100
) -> tuple[int, int]:
    """Persist one issue (via a zero-credit refresh) and return (series_id,
    issue_id) so a test can drive :func:`reconcile_issue_credits` directly."""
    sid = await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    await _run_refresh(
        db, settings, sid, commands,
        FakeCV().volume(1).issues(1, [issue(cv_issue_id, "1", credits=[])]),
    )
    return sid, await _issue_id_for_cv(db, sid, cv_issue_id)


@pytest.mark.req("FRG-CRTR-002")
async def test_idempotent_re_reconcile_and_drop_via_detail_path(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """The per-issue reconcile the detail path reuses is idempotent and applies
    drops (spec: refreshed twice with identical data changes no rows; a run that
    drops one credit removes exactly that association)."""
    sid, issue_id = await _persist_zero_credit_issue(
        db, settings, commands, root_folder_path, format_profile_id
    )
    two = (
        CreditRecord(10, "Alice", "writer", "writer"),
        CreditRecord(10, "Alice", "penciler", "penciler"),
    )
    async with db.write_session() as session:
        await reconcile_issue_credits(session, issue_id, two)
    first = {c.id for c in await _credits_for_series(db, sid)}
    assert {c.role_normalized for c in await _credits_for_series(db, sid)} == {
        "writer",
        "penciler",
    }

    # Identical detail credits again -> no row churn (stable ids).
    async with db.write_session() as session:
        await reconcile_issue_credits(session, issue_id, two)
    assert {c.id for c in await _credits_for_series(db, sid)} == first

    # Drop the penciler credit -> exactly that association is removed.
    async with db.write_session() as session:
        await reconcile_issue_credits(
            session, issue_id, (CreditRecord(10, "Alice", "writer", "writer"),)
        )
    assert {c.role_normalized for c in await _credits_for_series(db, sid)} == {"writer"}


@pytest.mark.req("FRG-CRTR-002")
async def test_verbatim_only_change_updates_row_in_place(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """A verbatim-only role change (same normalized slot) refreshes the stored
    verbatim in place — CV is authority for that column too — without churning
    the row identity, and an identical repeat writes nothing."""
    sid, issue_id = await _persist_zero_credit_issue(
        db, settings, commands, root_folder_path, format_profile_id
    )
    # "penciller" normalizes to "penciler" but is retained verbatim.
    async with db.write_session() as session:
        await reconcile_issue_credits(
            session, issue_id, (CreditRecord(10, "Alice", "penciller", "penciler"),)
        )
    rows = await _credits_for_series(db, sid)
    assert len(rows) == 1
    original_id = rows[0].id
    assert rows[0].role_normalized == "penciler"
    assert rows[0].role_verbatim == "penciller"

    # Only the verbatim spelling changes; the normalized key ("penciler") is
    # unchanged, so the SAME row must be updated (stable id), not deleted+re-added.
    async with db.write_session() as session:
        await reconcile_issue_credits(
            session, issue_id, (CreditRecord(10, "Alice", "penciler", "penciler"),)
        )
    rows = await _credits_for_series(db, sid)
    assert len(rows) == 1
    assert rows[0].id == original_id  # row identity preserved
    assert rows[0].role_verbatim == "penciler"  # verbatim re-authored by CV


@pytest.mark.req("FRG-CRTR-002")
async def test_partial_fetch_never_deletes_credits(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
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


# --- FRG-CRTR-004: explicit-only follows (no derived follow) -----------------


async def _credit_alice_across_series(
    db, settings, commands, root_folder_path, format_profile_id, cv_volume_ids
) -> int:
    """Refresh each of ``cv_volume_ids`` crediting Alice (cv 10); return her id.

    Each series ``v`` gets a single issue with cv id ``100 * v`` so re-refreshing
    a series by volume can address the same issue.
    """
    for cv_volume_id in cv_volume_ids:
        sid = await _make_series(
            db, root_folder_path, format_profile_id, cv_volume_id=cv_volume_id
        )
        fake = FakeCV().volume(cv_volume_id).issues(
            cv_volume_id,
            [issue(100 * cv_volume_id, "1", credits=[credit(10, "Alice", "writer")])],
        )
        await _run_refresh(db, settings, sid, commands, fake)
    return (await _creator_by_name(db, "Alice")).id


@pytest.mark.req("FRG-CRTR-004")
async def test_reconcile_never_derives_a_follow_even_across_many_series(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """Tripwire: a creator credited in THREE distinct library series is never
    auto-followed. Reconciliation does not seed, default, or otherwise derive
    ``followed`` (owner decision 2026-07-11) — only the explicit API sets it."""
    await _credit_alice_across_series(
        db, settings, commands, root_folder_path, format_profile_id, [1, 2, 3]
    )
    alice = await _creator_by_name(db, "Alice")
    assert alice.followed is False
    assert alice.follow_touched is None
    assert alice.followed_at is None


@pytest.mark.req("FRG-CRTR-004")
async def test_user_follow_is_never_overwritten_by_refresh(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """A user's explicit follow survives later refreshes — reconciliation never
    writes ``followed`` in either direction (FRG-CRTR-004 user-toggle scenario)."""
    alice_id = await _credit_alice_across_series(
        db, settings, commands, root_folder_path, format_profile_id, [1, 2]
    )
    async with db.write_session() as session:
        await creators_repo.set_creator_followed(session, alice_id, True)

    # Re-refresh both series -> the explicit follow is untouched.
    await _refresh_by_cv_volume(
        db, settings, commands, 1,
        FakeCV().volume(1).issues(
            1, [issue(100, "1", credits=[credit(10, "Alice", "writer")])]
        ),
    )
    await _refresh_by_cv_volume(
        db, settings, commands, 2,
        FakeCV().volume(2).issues(
            2, [issue(200, "1", credits=[credit(10, "Alice", "writer")])]
        ),
    )

    alice = await _creator_by_cv(db, 10)
    assert alice.followed is True
    assert alice.follow_touched is not None


@pytest.mark.req("FRG-CRTR-004")
async def test_user_unfollow_survives_prune_and_is_never_re_followed(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """A user-unfollowed creator who becomes creditless survives the prune (the
    touched predicate spares her, preserving the unfollow memory), and a later
    re-ingest never re-follows her — reconciliation derives no follow."""
    alice_id = await _credit_alice_across_series(
        db, settings, commands, root_folder_path, format_profile_id, [1, 2]
    )
    async with db.write_session() as session:
        await creators_repo.set_creator_followed(session, alice_id, False)

    # Drop Alice's issues entirely (a complete walk with the issue gone) so her
    # credits cascade and she becomes creditless — but touched, so prune spares
    # her. (Re-fetching stamped issues to observe an emptied credit list is an
    # explicit non-goal, so credits are dropped by deleting the issue instead.)
    await _refresh_by_cv_volume(db, settings, commands, 1, FakeCV().volume(1))
    await _refresh_by_cv_volume(db, settings, commands, 2, FakeCV().volume(2))
    alice = await _creator_by_cv(db, 10)
    assert alice is not None  # survived the creditless period
    assert alice.followed is False
    assert alice.follow_touched is not None

    # Re-ingest Alice into both series -> still unfollowed; reconciliation never
    # re-follows the deliberately-unfollowed creator.
    await _refresh_by_cv_volume(
        db, settings, commands, 1,
        FakeCV().volume(1).issues(
            1, [issue(100, "1", credits=[credit(10, "Alice", "writer")])]
        ),
    )
    await _refresh_by_cv_volume(
        db, settings, commands, 2,
        FakeCV().volume(2).issues(
            2, [issue(200, "1", credits=[credit(10, "Alice", "writer")])]
        ),
    )
    alice = await _creator_by_cv(db, 10)
    assert alice.followed is False


@pytest.mark.req("FRG-CRTR-002")
async def test_followed_creator_survives_prune(
    db, settings, commands, root_folder_id, root_folder_path, format_profile_id
):
    """A currently-FOLLOWED creator with zero remaining credits survives the
    prune — the ``followed`` predicate spares her, so an explicit follow is never
    silently erased by a later refresh that drops all her credits."""
    alice_id = await _credit_alice_across_series(
        db, settings, commands, root_folder_path, format_profile_id, [1, 2]
    )
    async with db.write_session() as session:
        await creators_repo.set_creator_followed(session, alice_id, True)

    # Drop Alice's issues entirely (complete walk, issue gone) so her credits
    # cascade and she becomes creditless -> followed, so prune spares her.
    await _refresh_by_cv_volume(db, settings, commands, 1, FakeCV().volume(1))
    await _refresh_by_cv_volume(db, settings, commands, 2, FakeCV().volume(2))

    alice = await _creator_by_cv(db, 10)
    assert alice is not None  # survived the creditless prune
    assert alice.followed is True
    assert alice.follow_touched is not None  # explicit follow stamped the marker
