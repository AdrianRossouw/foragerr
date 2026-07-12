"""Collected-edition reconciliation never suppresses singles (FRG-SRC-007).

Extends the FRG-SER-019 invariant to sources: reconciling a matched collected
edition marks the singles it fills owned-via-edition WITHOUT touching an already-
owned single, without double-counting bytes, and without ever writing a wanted-
suppression — the only wanted transition it produces is "issue becomes owned"
(an ``issue_files`` row), proven the same three ways as FRG-SER-019.
"""

from __future__ import annotations

import inspect

import pytest

from foragerr.library import repo
from foragerr.library.booktype import detect_series_booktype
from foragerr.library.containment import RangeInput, replace_issue_collections
from foragerr.sources import reconcile
from foragerr.sources.reconcile import (
    FILLABLE,
    OWNED_EDITION,
    OWNED_SINGLE,
    apply_owned_via_edition,
    compute_fill_set,
    revert_owned_via_edition,
)
from sources_support import (  # noqa: F401 — imported fixtures
    format_profile_id,
    root_folder_id,
)

EDITION_FILE = "/tmp/comics/synthetic-hero-collected.cbz"


async def _run(db, root_folder_id, format_profile_id, *, cvid, title, n):
    """A monitored singles run of ``n`` file-less, released (dates-null) issues."""
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=cvid,
            title=title,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=f"/tmp/comics/{title} ({cvid})",
        )
        ids = []
        for i in range(1, n + 1):
            issue = await repo.create_issue(
                session,
                series_id=series.id,
                cv_issue_id=cvid * 100 + i,
                issue_number=str(i),
                monitored=True,
            )
            ids.append(issue.id)
        return series.id, ids


async def _trade(db, root_folder_id, format_profile_id, *, cvid, title):
    """A trade-typed series with one owned trade issue (its own file)."""
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=cvid,
            title=title,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=f"/tmp/comics/{title} ({cvid})",
        )
        series.booktype = detect_series_booktype(title) or "tpb"
        issue = await repo.create_issue(
            session,
            series_id=series.id,
            cv_issue_id=cvid * 100 + 1,
            issue_number="1",
            monitored=True,
        )
        await repo.add_issue_file(
            session, issue_id=issue.id, path=EDITION_FILE, size=250_000
        )
        return series.id, issue.id


async def _declare(db, trade_issue_id, run_id, start_issue_id, end_issue_id):
    async with db.write_session() as session:
        await replace_issue_collections(
            session,
            trade_issue_id,
            [
                RangeInput(
                    target_series_id=run_id,
                    start_issue_id=start_issue_id,
                    end_issue_id=end_issue_id,
                )
            ],
        )


async def _own_single(db, issue_id, *, size=9000):
    async with db.write_session() as session:
        await repo.add_issue_file(
            session, issue_id=issue_id, path=f"/tmp/comics/single-{issue_id}.cbz", size=size
        )


@pytest.fixture
async def scenario(db, root_folder_id, format_profile_id):
    """Run #1–6 (with #3 owned as a single) + a trade collecting #1–6."""
    run_id, issue_ids = await _run(
        db, root_folder_id, format_profile_id, cvid=100, title="Synthetic Hero", n=6
    )
    trade_id, trade_issue_id = await _trade(
        db, root_folder_id, format_profile_id, cvid=200, title="Synthetic Hero HC"
    )
    await _declare(db, trade_issue_id, run_id, issue_ids[0], issue_ids[5])
    await _own_single(db, issue_ids[2])  # #3 owned as a single
    return {
        "run_id": run_id,
        "issue_ids": issue_ids,
        "trade_issue_id": trade_issue_id,
    }


# --- fill-set computation + owned-single preservation ------------------------


@pytest.mark.req("FRG-SRC-007")
async def test_fill_set_partitions_owned_single_from_fillable(db, scenario):
    async with db.read_session() as session:
        fs = await compute_fill_set(
            session, trade_issue_id=scenario["trade_issue_id"]
        )
    assert fs.standalone is False
    assert len(fs.ranges) == 1
    owns = {i.issue_id: i.ownership for r in fs.ranges for i in r.issues}
    # #3 is owned as a single (preserved); the rest are fillable.
    third = scenario["issue_ids"][2]
    assert owns[third] == OWNED_SINGLE
    assert sorted(fs.fillable_ids) == sorted(
        i for i in scenario["issue_ids"] if i != third
    )


@pytest.mark.req("FRG-SRC-007")
async def test_edition_fills_only_unowned_and_leaves_wanted_correctly(db, scenario):
    run_id = scenario["run_id"]
    third = scenario["issue_ids"][2]

    async with db.read_session() as session:
        before = set(await repo.wanted_issue_ids(session))
    # #3 owned → wanted is the other five.
    assert before == {i for i in scenario["issue_ids"] if i != third}

    async with db.write_session() as session:
        filled = await apply_owned_via_edition(
            session,
            trade_issue_id=scenario["trade_issue_id"],
            edition_file_path=EDITION_FILE,
        )
    assert filled == 5  # #1,2,4,5,6 filled; #3 skipped (already owned)

    async with db.read_session() as session:
        after = set(await repo.wanted_issue_ids(session))
        stats = await repo.series_statistics(session, run_id)
    # The only wanted transition: filled singles become owned → wanted empty.
    assert after == set()
    # No double-counting: file_count is all six, size is #3's single only
    # (edition rows are size 0 — the collected file's bytes counted once).
    assert stats.file_count == 6
    assert stats.missing_count == 0
    assert stats.size_on_disk == 9000

    # #3's own single file is untouched (never replaced).
    async with db.read_session() as session:
        from sqlalchemy import select

        from foragerr.library.models import IssueFileRow

        third_files = (
            (
                await session.execute(
                    select(IssueFileRow).where(IssueFileRow.issue_id == third)
                )
            )
            .scalars()
            .all()
        )
    assert len(third_files) == 1
    assert third_files[0].edition_issue_id is None  # still an owned single
    assert third_files[0].size == 9000


@pytest.mark.req("FRG-SRC-007")
async def test_apply_is_idempotent_and_revert_restores_wanted(db, scenario):
    for _ in range(2):
        async with db.write_session() as session:
            await apply_owned_via_edition(
                session,
                trade_issue_id=scenario["trade_issue_id"],
                edition_file_path=EDITION_FILE,
            )
    async with db.read_session() as session:
        stats = await repo.series_statistics(session, scenario["run_id"])
    assert stats.file_count == 6  # a second apply added no duplicate rows

    async with db.write_session() as session:
        reverted = await revert_owned_via_edition(
            session, trade_issue_id=scenario["trade_issue_id"]
        )
    assert reverted == 5
    async with db.read_session() as session:
        after = set(await repo.wanted_issue_ids(session))
    third = scenario["issue_ids"][2]
    # Unfilled singles return to wanted; #3 (real single) stays owned.
    assert after == {i for i in scenario["issue_ids"] if i != third}


@pytest.mark.req("FRG-SRC-007")
async def test_ogn_with_no_containment_is_standalone(
    db, root_folder_id, format_profile_id
):
    _run_id, _ids = await _run(
        db, root_folder_id, format_profile_id, cvid=300, title="Solo Run", n=3
    )
    _trade_id, trade_issue_id = await _trade(
        db, root_folder_id, format_profile_id, cvid=400, title="An Original GN"
    )
    # No containment declared → OGN/artbook standalone.
    async with db.read_session() as session:
        fs = await compute_fill_set(session, trade_issue_id=trade_issue_id)
    assert fs.standalone is True
    assert fs.ranges == ()

    async with db.write_session() as session:
        filled = await apply_owned_via_edition(
            session, trade_issue_id=trade_issue_id, edition_file_path=EDITION_FILE
        )
    assert filled == 0  # no singles fabricated


# --- three-way invariant proof (mirrors FRG-SER-019) ------------------------


@pytest.mark.req("FRG-SRC-007")
async def test_reconcile_never_writes_a_wanted_suppression(db, scenario):
    """No monitored flag changes; the wanted transition is ownership alone.

    An out-of-range wanted issue is added; after fill it must STILL be wanted
    (reconcile only fills the declared range) and every issue's monitored flag
    is unchanged.
    """
    from sqlalchemy import select

    from foragerr.library.models import IssueRow

    async with db.write_session() as session:
        extra = await repo.create_issue(
            session,
            series_id=scenario["run_id"],
            cv_issue_id=100 * 100 + 99,
            issue_number="99",
            monitored=True,
        )
        extra_id = extra.id

    async with db.read_session() as session:
        monitored_before = {
            r.id: r.monitored
            for r in (await session.execute(select(IssueRow))).scalars().all()
        }

    async with db.write_session() as session:
        await apply_owned_via_edition(
            session,
            trade_issue_id=scenario["trade_issue_id"],
            edition_file_path=EDITION_FILE,
        )

    async with db.read_session() as session:
        monitored_after = {
            r.id: r.monitored
            for r in (await session.execute(select(IssueRow))).scalars().all()
        }
        wanted = set(await repo.wanted_issue_ids(session))
    # Not one monitored flag moved (reconcile writes none).
    assert monitored_after == monitored_before
    # The out-of-range issue #99 is still wanted (never suppressed).
    assert extra_id in wanted


@pytest.mark.req("FRG-SRC-007")
def test_no_suppression_predicate_in_the_three_choke_points():
    """The mechanical arm: reconciliation's owned-via-edition marker never
    leaks into the wanted / statistics / pull-matcher predicates (FRG-SER-019
    extended), and reconcile itself writes no monitored flag."""
    from foragerr.pull import matching as pull_matching

    # (a) + (b): wanted_issues() / series_statistics carry no edition predicate.
    compiled_wanted = str(repo.wanted_issues()).lower()
    assert "edition_issue_id" not in compiled_wanted
    assert "issue_collections" not in compiled_wanted
    assert "booktype" not in compiled_wanted
    for fn in (repo.wanted_issues, repo.series_statistics):
        src = inspect.getsource(fn)
        assert "edition_issue_id" not in src
        assert "issue_collections" not in src

    # (c): the pull matcher never reads edition ownership.
    assert "edition_issue_id" not in inspect.getsource(pull_matching)

    # Reconciliation itself writes no monitored flag — ownership is the file row.
    recon_src = inspect.getsource(reconcile)
    assert ".monitored" not in recon_src


@pytest.mark.req("FRG-SER-019")
async def test_deleting_trade_issue_cascades_edition_rows_and_restores_wanted(
    db, scenario
):
    """edition_issue_id is a real FK with ON DELETE CASCADE: deleting the trade
    issue removes its owned-via-edition rows so the filled singles return to
    wanted (never silently suppressed by a dangling reference)."""
    from sqlalchemy import func, select

    from foragerr.library.models import IssueFileRow, IssueRow

    trade_issue_id = scenario["trade_issue_id"]
    third = scenario["issue_ids"][2]

    async with db.write_session() as session:
        await apply_owned_via_edition(
            session, trade_issue_id=trade_issue_id, edition_file_path=EDITION_FILE
        )
    async with db.read_session() as session:
        n = (
            await session.execute(
                select(func.count())
                .select_from(IssueFileRow)
                .where(IssueFileRow.edition_issue_id == trade_issue_id)
            )
        ).scalar_one()
    assert n == 5

    # Delete the trade issue → the cascade removes every edition row it provided.
    async with db.write_session() as session:
        trade_issue = await session.get(IssueRow, trade_issue_id)
        await session.delete(trade_issue)

    async with db.read_session() as session:
        remaining = (
            await session.execute(
                select(func.count())
                .select_from(IssueFileRow)
                .where(IssueFileRow.edition_issue_id == trade_issue_id)
            )
        ).scalar_one()
        wanted = set(await repo.wanted_issue_ids(session))
    assert remaining == 0
    # The five formerly-filled singles are wanted again; #3 (real single) is not.
    assert wanted == {i for i in scenario["issue_ids"] if i != third}


@pytest.mark.req("FRG-SRC-007")
async def test_revert_for_series_cleans_editions_but_keeps_real_singles(db, scenario):
    """The un-match/ignore cleanup reverts a whole matched series' edition fills
    without touching real single files (FRG-SRC-004/007)."""
    from foragerr.sources.reconcile import revert_owned_via_edition_for_series

    trade_issue_id = scenario["trade_issue_id"]
    third = scenario["issue_ids"][2]
    async with db.write_session() as session:
        await apply_owned_via_edition(
            session, trade_issue_id=trade_issue_id, edition_file_path=EDITION_FILE
        )

    # The trade series id is the series of the trade issue.
    from foragerr.library.models import IssueRow

    async with db.read_session() as session:
        trade_series_id = (await session.get(IssueRow, trade_issue_id)).series_id

    async with db.write_session() as session:
        reverted = await revert_owned_via_edition_for_series(
            session, series_id=trade_series_id
        )
    assert reverted == 5

    async with db.read_session() as session:
        wanted = set(await repo.wanted_issue_ids(session))
    # Singles back to wanted; #3's real single is preserved (still owned).
    assert wanted == {i for i in scenario["issue_ids"] if i != third}


@pytest.mark.req("FRG-SRC-007")
async def test_fill_set_reports_edition_owned_after_apply(db, scenario):
    async with db.write_session() as session:
        await apply_owned_via_edition(
            session,
            trade_issue_id=scenario["trade_issue_id"],
            edition_file_path=EDITION_FILE,
        )
    async with db.read_session() as session:
        fs = await compute_fill_set(
            session, trade_issue_id=scenario["trade_issue_id"]
        )
    owns = {i.issue_id: i.ownership for r in fs.ranges for i in r.issues}
    third = scenario["issue_ids"][2]
    assert owns[third] == OWNED_SINGLE
    assert all(
        owns[i] == OWNED_EDITION
        for i in scenario["issue_ids"]
        if i != third
    )
    assert FILLABLE not in owns.values()
