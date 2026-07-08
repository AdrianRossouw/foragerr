"""Volume grouping: franchise-key derivation, auto-grouping at add/refresh, and
the wanted/statistics NON-REGRESSION proof (FRG-SER-016).

The correctness core is the invariant that grouping is DISPLAY-ONLY: setting a
series' ``series_group_id`` must leave ``wanted_issues()`` and
``series_statistics`` byte-identical (no group predicate reaches the choke
point). ``test_grouping_never_alters_wanted_or_statistics`` proves it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.commands import CommandService
from foragerr.library import repo
from foragerr.library.grouping import (
    franchise_display_title,
    franchise_key,
)
from foragerr.library.flows import add_series, refresh_series
from foragerr.library.models import SeriesGroupRow

from flows_support import FakeCV, build_factory, flows_settings, issue


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


@pytest.fixture
async def commands(db, settings, command_registry):
    return CommandService(db, settings)


# --- franchise_key unit tests (pure) ----------------------------------------


@pytest.mark.req("FRG-SER-016")
def test_franchise_key_folds_successive_runs_of_one_title():
    # Batman (2011) and Batman (2016) are two CV volumes of one franchise.
    assert franchise_key("Batman (2011)") == franchise_key("Batman (2016)")
    assert franchise_key("Batman (2011)") == "batman"


@pytest.mark.req("FRG-SER-016")
def test_franchise_key_keeps_distinct_titles_distinct():
    assert franchise_key("Batman (2011)") != franchise_key("Superman (2011)")
    assert franchise_key("Saga (2012)") != franchise_key("Paper Girls (2015)")


@pytest.mark.req("FRG-SER-016")
def test_franchise_key_strips_trailing_volume_designator():
    assert franchise_key("Ultimate Spider-Man Vol 2") == franchise_key(
        "Ultimate Spider-Man"
    )
    assert franchise_key("X-Men Volume 3") == franchise_key("X-Men")
    assert franchise_key("Hellboy Vol. 4") == franchise_key("Hellboy")


@pytest.mark.req("FRG-SER-016")
def test_franchise_key_strips_stacked_year_and_volume():
    assert franchise_key("Batman Vol 2 (2016)") == "batman"


@pytest.mark.req("FRG-SER-016")
def test_franchise_key_empty_and_designator_only_edges_return_none():
    assert franchise_key("") is None
    assert franchise_key("   ") is None
    assert franchise_key("(2011)") is None
    assert franchise_key("Vol 2") is None


@pytest.mark.req("FRG-SER-016")
def test_franchise_display_title_preserves_casing_and_glyphs():
    assert franchise_display_title("Batman (2011)") == "Batman"
    assert franchise_display_title("Ultimate Spider-Man Vol 2") == "Ultimate Spider-Man"


@pytest.mark.req("FRG-SER-016")
def test_franchise_key_leaves_a_midtitle_year_alone():
    # Only a *trailing* year is a volume designator; a year inside the title is
    # part of the name and must not be stripped (no over-merging).
    assert franchise_key("2000 AD") == matching_key_of("2000 AD")


def matching_key_of(title: str) -> str:
    from foragerr.parser.normalize import matching_key

    return matching_key(title)


# --- auto-grouping at add + refresh -----------------------------------------


async def _add(db, settings, commands, root_folder_id, *, cv_volume_id, name):
    factory = build_factory(settings, FakeCV().volume(cv_volume_id, name=name).handler())
    result = await add_series(
        db,
        settings,
        cv_volume_id=cv_volume_id,
        root_folder_id=root_folder_id,
        commands=commands,
        enqueue_refresh=False,
        factory=factory,
    )
    return result.series.id


@pytest.mark.req("FRG-SER-016")
async def test_two_runs_of_a_title_share_one_group_after_add(
    db, settings, commands, root_folder_id, format_profile_id
):
    a = await _add(db, settings, commands, root_folder_id, cv_volume_id=1, name="Batman (2011)")
    b = await _add(db, settings, commands, root_folder_id, cv_volume_id=2, name="Batman (2016)")

    async with db.read_session() as session:
        sa = await repo.get_series(session, a)
        sb = await repo.get_series(session, b)
        groups = (await session.execute(select(SeriesGroupRow))).scalars().all()

    assert sa.series_group_id is not None
    assert sa.series_group_id == sb.series_group_id
    assert len(groups) == 1
    assert groups[0].title == "Batman"
    assert groups[0].grouping_key == "batman"


@pytest.mark.req("FRG-SER-016")
async def test_empty_key_series_stays_ungrouped_after_add(
    db, settings, commands, root_folder_id, format_profile_id
):
    # A CV volume with no name falls back to "Volume <id>", which has a real
    # key; to exercise the empty-key path we set the title to a year only.
    sid = await _add(db, settings, commands, root_folder_id, cv_volume_id=7, name="(2011)")
    async with db.read_session() as session:
        s = await repo.get_series(session, sid)
    assert s.series_group_id is None


@pytest.mark.req("FRG-SER-016")
async def test_refresh_keeps_grouping(
    db, settings, commands, root_folder_id, format_profile_id
):
    sid = await _add(db, settings, commands, root_folder_id, cv_volume_id=3, name="Saga (2012)")
    async with db.read_session() as session:
        group_before = (await repo.get_series(session, sid)).series_group_id
    assert group_before is not None

    factory = build_factory(
        settings,
        FakeCV().volume(3, name="Saga (2012)").issues(3, [issue(300, "1")]).handler(),
    )
    await refresh_series(db, settings, sid, commands=commands, factory=factory)

    async with db.read_session() as session:
        s = await repo.get_series(session, sid)
    assert s.series_group_id == group_before  # same group, not re-created


# --- A.5 non-regression: grouping never alters wanted/statistics ------------


@pytest.mark.req("FRG-SER-016")
async def test_grouping_never_alters_wanted_or_statistics(
    db, root_folder_id, format_profile_id
):
    """The invariant proof: a series' wanted-issue ids and full statistics are
    byte-identical before and after it is placed in a franchise group."""
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=100,
            title="Batman (2011)",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Batman (2011)",
        )
        sid = series.id
        i1 = await repo.create_issue(
            session,
            series_id=sid,
            cv_issue_id=1000,
            issue_number="1",
            cover_date=dt.date(2011, 1, 1),
        )
        await repo.create_issue(
            session,
            series_id=sid,
            cv_issue_id=1001,
            issue_number="2",
            cover_date=dt.date(2011, 2, 1),
        )
        await repo.add_issue_file(session, issue_id=i1.id, path="/tmp/comics/b1.cbz", size=10)

    async with db.read_session() as session:
        wanted_before = await repo.wanted_issue_ids(session)
        stats_before = await repo.series_statistics(session, sid)
        assert (await repo.get_series(session, sid)).series_group_id is None

    # Group the series (auto-derivation).
    async with db.write_session() as session:
        series = await repo.get_series(session, sid)
        await repo.apply_autogrouping(session, series)
        assert series.series_group_id is not None

    async with db.read_session() as session:
        wanted_after = await repo.wanted_issue_ids(session)
        stats_after = await repo.series_statistics(session, sid)

    assert wanted_after == wanted_before
    assert stats_after == stats_before
