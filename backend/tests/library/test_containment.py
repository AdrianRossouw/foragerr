"""Trade containment repo layer (FRG-SER-020 / FRG-API-022 read/write core).

Covers the declared-range round-trip (incl. non-contiguous "#1–#6" + "#8"),
the chip and rollup reads with request-time coverage, write validation, the
delete cascades, and the never-touches-wanted invariant at the repo level.
The compiled-SQL absence proof (containment reaches neither wanted nor stats)
lives alongside the FRG-SER-019 proof in test_trade_non_suppression.py.
"""

from __future__ import annotations

import datetime as dt

import pytest

from foragerr.library import containment, repo
from foragerr.library.containment import (
    ContainmentNotFoundError,
    ContainmentValidationError,
    RangeInput,
)


async def _make_target_series(
    db, root_folder_id, format_profile_id, *, cv_volume_id, title, numbers, owned=()
):
    """A single-issues series with issues numbered ``numbers``; those whose
    number is in ``owned`` get a file. Returns (series_id, {number: issue_id})."""
    owned_set = set(owned)
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title=title,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=f"/tmp/comics/{title} ({cv_volume_id})",
        )
        ids: dict[str, int] = {}
        for i, number in enumerate(numbers, start=1):
            iss = await repo.create_issue(
                session,
                series_id=series.id,
                cv_issue_id=cv_volume_id * 1000 + i,
                issue_number=number,
                monitored=True,
            )
            ids[number] = iss.id
            if number in owned_set:
                await repo.add_issue_file(
                    session,
                    issue_id=iss.id,
                    path=f"/tmp/comics/{title}-{number}.cbz",
                    size=1000,
                )
        return series.id, ids


async def _make_trade(db, root_folder_id, format_profile_id, *, cv_volume_id, title):
    """A trade-typed series with a single collected-book issue. Returns
    (series_id, trade_issue_id)."""
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title=title,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=f"/tmp/comics/{title} ({cv_volume_id})",
        )
        series.booktype = "tpb"
        iss = await repo.create_issue(
            session,
            series_id=series.id,
            cv_issue_id=cv_volume_id * 1000 + 1,
            issue_number="1",
            cover_date=dt.date(2020, 1, 1),
            monitored=True,
        )
        return series.id, iss.id


@pytest.mark.req("FRG-SER-020")
async def test_declared_range_round_trips_including_non_contiguous(
    db, root_folder_id, format_profile_id
):
    target_id, issues = await _make_target_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=100, title="Saga", numbers=[str(n) for n in range(1, 9)],
    )
    _, trade_issue_id = await _make_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=200, title="Saga Vol 1 (TPB)"
    )

    async with db.write_session() as session:
        await containment.replace_issue_collections(
            session,
            trade_issue_id,
            [
                RangeInput(target_id, issues["1"], issues["6"]),
                RangeInput(target_id, issues["8"], issues["8"]),
            ],
        )

    async with db.read_session() as session:
        rows = await containment.list_issue_collections(session, trade_issue_id)
        # Ordering keys must match the chosen endpoint issues exactly.
        i1 = await repo.get_issue(session, issues["1"])
        i6 = await repo.get_issue(session, issues["6"])
        i8 = await repo.get_issue(session, issues["8"])

    assert len(rows) == 2
    by_label = {r.range_label: r for r in rows}
    assert set(by_label) == {"#1–#6", "#8"}
    assert by_label["#1–#6"].start_ordering_key == i1.ordering_key
    assert by_label["#1–#6"].end_ordering_key == i6.ordering_key
    assert by_label["#8"].start_ordering_key == i8.ordering_key
    assert by_label["#8"].end_ordering_key == i8.ordering_key
    assert all(r.target_series_id == target_id for r in rows)
    assert all(r.source == "declared" and r.confidence == 1.0 for r in rows)


@pytest.mark.req("FRG-SER-020")
async def test_replace_is_wholesale(db, root_folder_id, format_profile_id):
    target_id, issues = await _make_target_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=101, title="Paper Girls", numbers=[str(n) for n in range(1, 7)],
    )
    _, trade_issue_id = await _make_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=201, title="Paper Girls TPB"
    )
    async with db.write_session() as session:
        await containment.replace_issue_collections(
            session, trade_issue_id, [RangeInput(target_id, issues["1"], issues["6"])]
        )
    # Re-declaring replaces, not appends.
    async with db.write_session() as session:
        await containment.replace_issue_collections(
            session, trade_issue_id, [RangeInput(target_id, issues["2"], issues["3"])]
        )
    async with db.read_session() as session:
        rows = await containment.list_issue_collections(session, trade_issue_id)
    assert [r.range_label for r in rows] == ["#2–#3"]

    # An empty replace clears everything.
    async with db.write_session() as session:
        await containment.replace_issue_collections(session, trade_issue_id, [])
    async with db.read_session() as session:
        assert await containment.list_issue_collections(session, trade_issue_id) == []


@pytest.mark.req("FRG-SER-020")
@pytest.mark.req("FRG-API-022")
async def test_validation_rejections(db, root_folder_id, format_profile_id):
    target_id, issues = await _make_target_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=102, title="Monstress", numbers=[str(n) for n in range(1, 7)],
    )
    other_id, other_issues = await _make_target_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=103, title="Descender", numbers=["1", "2"],
    )
    _, trade_issue_id = await _make_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=202, title="Monstress TPB"
    )

    # Endpoint from a DIFFERENT series than the named target -> field-precise 400.
    with pytest.raises(ContainmentValidationError) as exc:
        async with db.write_session() as session:
            await containment.replace_issue_collections(
                session,
                trade_issue_id,
                [RangeInput(target_id, other_issues["1"], issues["6"])],
            )
    assert exc.value.field == "start_issue_id"

    # Bounds out of order (start sorts after end).
    with pytest.raises(ContainmentValidationError) as exc:
        async with db.write_session() as session:
            await containment.replace_issue_collections(
                session, trade_issue_id, [RangeInput(target_id, issues["6"], issues["1"])]
            )
    assert exc.value.field == "end_issue_id"

    # Unknown target series.
    with pytest.raises(ContainmentValidationError) as exc:
        async with db.write_session() as session:
            await containment.replace_issue_collections(
                session, trade_issue_id, [RangeInput(999999, issues["1"], issues["6"])]
            )
    assert exc.value.field == "target_series_id"

    # A rejected declaration wrote nothing.
    async with db.read_session() as session:
        assert await containment.list_issue_collections(session, trade_issue_id) == []


@pytest.mark.req("FRG-SER-020")
@pytest.mark.req("FRG-API-022")
async def test_declaration_on_non_trade_issue_is_rejected(
    db, root_folder_id, format_profile_id
):
    target_id, issues = await _make_target_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=104, title="Wytches", numbers=["1", "2"],
    )
    # A single-issues (non-trade) series' issue cannot host containment.
    single_id, single_issues = await _make_target_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=105, title="Nailbiter", numbers=["1"],
    )
    with pytest.raises(ContainmentValidationError) as exc:
        async with db.write_session() as session:
            await containment.replace_issue_collections(
                session,
                single_issues["1"],
                [RangeInput(target_id, issues["1"], issues["2"])],
            )
    assert exc.value.field == "issue_id"

    with pytest.raises(ContainmentNotFoundError):
        async with db.write_session() as session:
            await containment.replace_issue_collections(
                session, 8675309, [RangeInput(target_id, issues["1"], issues["2"])]
            )


@pytest.mark.req("FRG-SER-020")
@pytest.mark.req("FRG-API-022")
async def test_self_containment_is_rejected(db, root_folder_id, format_profile_id):
    """A trade issue may not declare that it collects its OWN series — the
    target must be a different (single-issues) run."""
    trade_id, trade_issue_id = await _make_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=120, title="Ouroboros TPB"
    )
    # Give the trade series a second/third issue to use as endpoints against itself.
    async with db.write_session() as session:
        a = await repo.create_issue(
            session, series_id=trade_id, cv_issue_id=120_500, issue_number="2",
            monitored=True,
        )
        b = await repo.create_issue(
            session, series_id=trade_id, cv_issue_id=120_501, issue_number="3",
            monitored=True,
        )
        await session.flush()
        a_id, b_id = a.id, b.id

    with pytest.raises(ContainmentValidationError) as exc:
        async with db.write_session() as session:
            await containment.replace_issue_collections(
                session, trade_issue_id, [RangeInput(trade_id, a_id, b_id)]
            )
    assert exc.value.field == "target_series_id"


@pytest.mark.req("FRG-API-022")
async def test_collections_both_directions_with_resolved_endpoints(
    db, root_folder_id, format_profile_id
):
    """A trade-typed series' OWN collections read reflects the declarations its
    issues make (direction B), with each range's endpoints resolved back to the
    target series' issue ids so an edit dialog can pre-fill."""
    target_id, issues = await _make_target_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=130, title="Lazarus", numbers=[str(n) for n in range(1, 7)],
        owned=["1", "2", "3"],
    )
    trade_id, trade_issue_id = await _make_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=230, title="Lazarus Vol 1 TPB"
    )
    async with db.write_session() as session:
        await containment.replace_issue_collections(
            session, trade_issue_id, [RangeInput(target_id, issues["1"], issues["3"])]
        )

    # Reading the TRADE series' collections (direction B) surfaces its own
    # issue's declaration with resolved endpoint ids + coverage.
    async with db.read_session() as session:
        rollups = await containment.collections_for_series(session, trade_id)
    assert len(rollups) == 1
    rollup = rollups[0]
    assert rollup.trade_issue_id == trade_issue_id
    assert rollup.coverage == "collected"
    assert (rollup.issues_in_ranges, rollup.owned_in_ranges) == (3, 3)
    [rng] = rollup.ranges
    assert rng.target_series_id == target_id
    assert rng.start_issue_id == issues["1"]
    assert rng.end_issue_id == issues["3"]

    # Reading the TARGET series' collections (direction A) still surfaces the
    # same record, endpoints resolved identically.
    async with db.read_session() as session:
        a_rollups = await containment.collections_for_series(session, target_id)
    assert len(a_rollups) == 1
    [a_rng] = a_rollups[0].ranges
    assert (a_rng.start_issue_id, a_rng.end_issue_id) == (issues["1"], issues["3"])


@pytest.mark.req("FRG-API-022")
async def test_collected_in_chips_are_exact(db, root_folder_id, format_profile_id):
    target_id, issues = await _make_target_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=106, title="East of West", numbers=[str(n) for n in range(1, 9)],
    )
    trade_id, trade_issue_id = await _make_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=206, title="East of West TPB"
    )
    async with db.write_session() as session:
        await containment.replace_issue_collections(
            session,
            trade_issue_id,
            [
                RangeInput(target_id, issues["2"], issues["4"]),
                RangeInput(target_id, issues["7"], issues["7"]),
            ],
        )
    async with db.read_session() as session:
        chips = await containment.collected_in_for_series(session, target_id)

    # Exactly the issues inside a declared range carry a chip; others none.
    inside = {"2", "3", "4", "7"}
    assert {issues[n] for n in inside} == set(chips)
    for n in inside:
        [m] = chips[issues[n]]
        assert m.trade_series_id == trade_id
        assert m.trade_series_title == "East of West TPB"
        assert m.trade_issue_id == trade_issue_id
        assert m.booktype == "tpb"
    assert chips[issues["2"]][0].range_label == "#2–#4"
    assert chips[issues["7"]][0].range_label == "#7"
    # Issues outside every range carry nothing.
    for n in ("1", "5", "6", "8"):
        assert issues[n] not in chips


@pytest.mark.req("FRG-API-022")
async def test_collections_rollup_coverage(db, root_folder_id, format_profile_id):
    # #1–#3 owned, #4–#9 missing.
    target_id, issues = await _make_target_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=107, title="Deadly Class",
        numbers=[str(n) for n in range(1, 10)], owned=["1", "2", "3"],
    )
    _, collected_trade = await _make_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=207, title="DC Vol 1"
    )
    _, partial_trade = await _make_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=208, title="DC Deluxe"
    )
    _, none_trade = await _make_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=209, title="DC Vol 3"
    )
    async with db.write_session() as session:
        await containment.replace_issue_collections(
            session, collected_trade, [RangeInput(target_id, issues["1"], issues["3"])]
        )
        await containment.replace_issue_collections(
            session, partial_trade, [RangeInput(target_id, issues["1"], issues["6"])]
        )
        await containment.replace_issue_collections(
            session, none_trade, [RangeInput(target_id, issues["7"], issues["9"])]
        )

    async with db.read_session() as session:
        rollups = await containment.collections_for_series(session, target_id)
    by_trade = {r.trade_issue_id: r for r in rollups}

    assert by_trade[collected_trade].coverage == "collected"
    assert (by_trade[collected_trade].issues_in_ranges, by_trade[collected_trade].owned_in_ranges) == (3, 3)
    assert by_trade[partial_trade].coverage == "partial"
    assert (by_trade[partial_trade].issues_in_ranges, by_trade[partial_trade].owned_in_ranges) == (6, 3)
    assert by_trade[none_trade].coverage == "none"
    assert (by_trade[none_trade].issues_in_ranges, by_trade[none_trade].owned_in_ranges) == (3, 0)
    # Each rollup carries its range labels + the trade issue's cover date.
    assert [r.label for r in by_trade[collected_trade].ranges] == ["#1–#3"]
    assert by_trade[collected_trade].release_date == dt.date(2020, 1, 1)


@pytest.mark.req("FRG-SER-020")
async def test_cascade_on_trade_issue_delete(db, root_folder_id, format_profile_id):
    target_id, issues = await _make_target_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=110, title="Pretty Deadly", numbers=["1", "2", "3"],
    )
    _, trade_issue_id = await _make_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=210, title="Pretty Deadly TPB"
    )
    async with db.write_session() as session:
        await containment.replace_issue_collections(
            session, trade_issue_id, [RangeInput(target_id, issues["1"], issues["3"])]
        )
    # Deleting the trade issue removes its containment and nothing else.
    async with db.write_session() as session:
        await session.delete(await repo.get_issue(session, trade_issue_id))

    async with db.read_session() as session:
        assert await containment.list_issue_collections(session, trade_issue_id) == []
        # The target series' issues + files are untouched — including their
        # monitored flags (containment is display-only, never a wanted lever).
        target_issues = await repo.list_issues_for_series(session, target_id)
        assert len(target_issues) == 3
        assert all(i.monitored for i in target_issues)


@pytest.mark.req("FRG-SER-020")
async def test_cascade_on_target_series_delete(db, root_folder_id, format_profile_id):
    target_id, issues = await _make_target_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=111, title="Bitch Planet", numbers=["1", "2"],
    )
    _, trade_issue_id = await _make_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=211, title="Bitch Planet TPB"
    )
    async with db.write_session() as session:
        await containment.replace_issue_collections(
            session, trade_issue_id, [RangeInput(target_id, issues["1"], issues["2"])]
        )
    async with db.write_session() as session:
        await session.delete(await repo.get_series(session, target_id))

    async with db.read_session() as session:
        assert await containment.list_issue_collections(session, trade_issue_id) == []
        # The trade issue itself survives (only its dangling record went).
        assert await repo.get_issue(session, trade_issue_id) is not None


@pytest.mark.req("FRG-SER-020")
async def test_declaring_containment_never_changes_wanted(
    db, root_folder_id, format_profile_id
):
    """Declaring (and deleting) containment over a fully-file-backed range
    changes no issue's wanted state — containment is display-only."""
    target_id, issues = await _make_target_series(
        db, root_folder_id, format_profile_id,
        cv_volume_id=112, title="Wicked + Divine",
        numbers=[str(n) for n in range(1, 7)], owned=["1", "2", "3"],
    )
    _, trade_issue_id = await _make_trade(
        db, root_folder_id, format_profile_id, cv_volume_id=212, title="WicDiv TPB"
    )

    async with db.read_session() as session:
        wanted_before = set(await repo.wanted_issue_ids(session))
        stats_before = await repo.series_statistics(session, target_id)

    async with db.write_session() as session:
        await containment.replace_issue_collections(
            session, trade_issue_id, [RangeInput(target_id, issues["1"], issues["3"])]
        )
    async with db.read_session() as session:
        wanted_after_declare = set(await repo.wanted_issue_ids(session))
        stats_after_declare = await repo.series_statistics(session, target_id)

    async with db.write_session() as session:
        await containment.delete_issue_collections(session, trade_issue_id)
    async with db.read_session() as session:
        wanted_after_delete = set(await repo.wanted_issue_ids(session))

    assert wanted_after_declare == wanted_before
    assert wanted_after_delete == wanted_before
    assert stats_after_declare == stats_before
