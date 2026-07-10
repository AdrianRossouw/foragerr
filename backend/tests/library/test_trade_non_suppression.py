"""Trades never suppress single-issue wanted (FRG-SER-019) — the correctness
core of the trade-typing change.

A series' collected-edition typing, and ownership of a full trade line, SHALL
NOT remove, hide, or de-prioritise any single issue from wanted/missing state.
This is guaranteed structurally: no book-type predicate exists in
`repo.wanted_issues()` or `repo.series_statistics`, and a trade is a separate
ComicVine volume -> separate series, so its files attach only to its own
trade-line issues. These tests pin that invariant:

(a) a fully-owned collected-edition series of the same title leaves every
    single issue of the single-issues series still wanted; and
(b) typing a series (auto or manual) leaves `wanted_issues` / `series_statistics`
    output byte-identical to before typing.

The pull-matcher arm of the invariant (its book-type guard still matches a
typed line's entries) lives in tests/pull/test_pull_trade_typing.py.
"""

from __future__ import annotations

import inspect

import pytest

from foragerr.library import repo
from foragerr.library.booktype import detect_series_booktype
from foragerr.library.flows import BooktypeEdit, edit_series


async def _make_single_series(db, root_folder_id, format_profile_id, *, cv_volume_id, title, n):
    """A monitored single-issues series with ``n`` monitored, file-less,
    released (both dates null) issues — so all ``n`` are wanted."""
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title=title,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=f"/tmp/comics/{title} ({cv_volume_id})",
        )
        ids = []
        for i in range(1, n + 1):
            iss = await repo.create_issue(
                session,
                series_id=series.id,
                cv_issue_id=cv_volume_id * 100 + i,
                issue_number=str(i),
                monitored=True,
            )
            ids.append(iss.id)
        return series.id, ids


async def _make_owned_trade(db, root_folder_id, format_profile_id, *, cv_volume_id, title):
    """A separate-volume collected-edition series (same title) whose single
    trade-line issue is fully owned (has a file) and typed as a trade."""
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title=title,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=f"/tmp/comics/{title} ({cv_volume_id})",
        )
        series.booktype = detect_series_booktype(title) or "tpb"
        iss = await repo.create_issue(
            session,
            series_id=series.id,
            cv_issue_id=cv_volume_id * 100 + 1,
            issue_number="1",
            monitored=True,
        )
        await repo.add_issue_file(
            session, issue_id=iss.id, path=f"/tmp/comics/{title}-trade.cbz", size=9000
        )
        return series.id, iss.id


@pytest.mark.req("FRG-SER-019")
async def test_owning_a_full_trade_line_leaves_single_issues_wanted(
    db, root_folder_id, format_profile_id
):
    single_id, single_issue_ids = await _make_single_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=100, title="Saga (TPB)", n=3,
    )
    # Baseline: with no trade in the library, all three singles are wanted.
    async with db.read_session() as session:
        before = set(await repo.wanted_issue_ids(session))
        stats_before = await repo.series_statistics(session, single_id)
    assert set(single_issue_ids) <= before
    assert stats_before.missing_count == 3

    # Add a fully-owned, trade-typed series of the SAME title (separate volume).
    trade_id, trade_issue_id = await _make_owned_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=200, title="Saga (TPB)"
    )

    async with db.read_session() as session:
        after = set(await repo.wanted_issue_ids(session))
        stats_after = await repo.series_statistics(session, single_id)
        trade_stats = await repo.series_statistics(session, trade_id)

    # Every single issue that was wanted is STILL wanted — the trade changed
    # nothing about the singles.
    assert set(single_issue_ids) <= after
    assert stats_after.missing_count == 3
    # The owned trade issue is (correctly) not wanted, and never appears among
    # the singles' wanted ids.
    assert trade_issue_id not in after
    assert trade_stats.missing_count == 0
    # The single series' own wanted set is untouched by the trade's existence.
    assert {i for i in before if i in single_issue_ids} == {
        i for i in after if i in single_issue_ids
    }


@pytest.mark.req("FRG-SER-019")
async def test_typing_a_series_does_not_alter_wanted_or_statistics(
    db, root_folder_id, format_profile_id
):
    """Typing a single-issues series as a collected edition (auto-derived cue
    title OR an explicit manual override) leaves `wanted_issues` and
    `series_statistics` output byte-identical — no book-type predicate reaches
    either computation."""
    series_id, issue_ids = await _make_single_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=300, title="Paper Girls", n=4,
    )
    # Own two of the four so missing_count is a non-trivial number.
    async with db.write_session() as session:
        for iss_id in issue_ids[:2]:
            await repo.add_issue_file(
                session, issue_id=iss_id, path=f"/tmp/comics/pg-{iss_id}.cbz", size=1000
            )

    async with db.read_session() as session:
        wanted_before = await repo.wanted_issue_ids(session)
        stats_before = await repo.series_statistics(session, series_id)

    # Type it explicitly (manual override -> locked). Nothing about wanted or
    # stats may move.
    await edit_series(db, series_id, booktype_op=BooktypeEdit(action="set", booktype="tpb"))

    async with db.read_session() as session:
        row = await repo.get_series(session, series_id)
        assert row.booktype == "tpb"  # the typing really did apply
        wanted_after = await repo.wanted_issue_ids(session)
        stats_after = await repo.series_statistics(session, series_id)

    assert wanted_after == wanted_before
    assert stats_after == stats_before
    assert stats_after.missing_count == 2


@pytest.mark.req("FRG-SER-019")
@pytest.mark.req("FRG-SER-020")
def test_wanted_and_statistics_sql_never_reference_booktype_or_containment():
    """The absence proof, mechanically: neither the compiled ``wanted_issues``
    query nor the source of ``wanted_issues``/``series_statistics`` references
    the collected-edition ``booktype`` predicate (FRG-SER-019) OR the trade
    containment side table ``issue_collections`` (FRG-SER-020). Both are
    display-only; a predicate on either reaching the wanted/stats choke point
    would be the exact regression these invariants forbid."""
    forbidden = ("booktype", "issue_collections", "IssueCollectionRow")

    # The reusable "wanted" selectable compiles to SQL touching only
    # series/issues/issue_files — never the trade-typing or containment tables.
    compiled_wanted = str(repo.wanted_issues()).lower()
    assert "issue_files" in compiled_wanted  # sanity: it is the real query
    for token in forbidden:
        assert token.lower() not in compiled_wanted, (
            f"wanted_issues() SQL references {token!r}"
        )

    # series_statistics builds several small aggregates at request time rather
    # than one Select, so pin the absence at the source level (the same
    # technique, applied to a multi-statement function).
    for fn in (repo.wanted_issues, repo.series_statistics):
        src = inspect.getsource(fn)
        for token in forbidden:
            assert token not in src, f"{fn.__name__} references {token!r}"
