"""Provenance-authoritative series resolution + the ordinal fallback
(FRG-PP-021, FRG-PP-022).

A store grab records the series the operator matched an entitlement to and NO
issue id (``GrabHistoryRow(series_id=…, issue_id=None)``). These tests pin that
such a hint fixes the series — the filename is consulted for the ISSUE only —
and that a `Vol. N` file lands as issue N when, and only when, the known series
really holds it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.downloads.models import GrabHistoryRow
from foragerr.importer import history
from foragerr.importer.pipeline import ImportStatus, gather, import_candidate
from foragerr.importer.sources import CompletedDownloadSource, RescanSource
from foragerr.library import repo
from foragerr.library.models import IssueFileRow

from importer._archives import comicinfo_xml, make_cbz, make_cbz_with_comicinfo


async def _add_series_grab(db, *, download_id, series_id, title):
    """The store-grab shape: a series the operator matched, no issue id."""
    async with db.write_session() as session:
        session.add(
            GrabHistoryRow(
                download_id=download_id,
                series_id=series_id,
                issue_id=None,
                title=title,
                protocol="usenet",
                source="humble",
                created_at=dt.datetime(2026, 7, 5),
            )
        )


async def _add_issue(db, series_id, *, cv_issue_id, issue_number):
    async with db.write_session() as session:
        issue = await repo.create_issue(
            session,
            series_id=series_id,
            cv_issue_id=cv_issue_id,
            issue_number=issue_number,
        )
        return issue.id


async def _run(db, source, ctx):
    outcomes = []
    async with db.write_session() as session:
        for candidate in await gather(source, session, ctx):
            outcomes.append(await import_candidate(session, candidate, ctx))
    return outcomes


async def _issue_files(db):
    async with db.read_session() as session:
        return (await session.execute(select(IssueFileRow))).scalars().all()


async def _download(db, ctx, tmp_dir: Path, file_name: str, *, download_id: str):
    make_cbz(tmp_dir / file_name)
    return await _run(
        db,
        CompletedDownloadSource(download_id=download_id, output_path=str(tmp_dir)),
        ctx,
    )


# --- FRG-PP-021: the provenance series is authoritative ----------------------


@pytest.mark.req("FRG-PP-021")
async def test_series_only_grab_hint_resolves_the_issue_within_that_series(
    db, seed, import_ctx, tmp_path
):
    """The operator matched the entitlement to Strangelands; the file's own name
    parses to a series that does not exist in the library. The series comes from
    the grab record, the issue from the name — and the file imports."""
    s = await seed(title="Strangelands", issue_number="8", cv_volume_id=77,
                   cv_issue_id=7700)
    ctx = import_ctx()
    await _add_series_grab(
        db, download_id="hum-1", series_id=s.series_id, title="Strangelands Bundle"
    )

    outcomes = await _download(
        db, ctx, tmp_path / "hum1", "Some Other Name #8.cbz", download_id="hum-1"
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert (outcomes[0].series_id, outcomes[0].issue_id) == (s.series_id, s.issue_id)


@pytest.mark.req("FRG-PP-021")
async def test_provenance_series_beats_a_cleanly_parsed_other_series(
    db, seed, import_ctx, tmp_path
):
    """A filename that parses EXACTLY to another in-library series must not
    relocate the file: the operator's match outranks filename evidence, so the
    issue number resolves inside the provenance series (which holds its own
    #404) and the other series is never touched."""
    strangelands = await seed(
        title="Strangelands", issue_number="8", cv_volume_id=77, cv_issue_id=7700
    )
    own_404 = await _add_issue(
        db, strangelands.series_id, cv_issue_id=7704, issue_number="404"
    )
    daredevil = await seed(
        title="Daredevil", issue_number="404", cv_volume_id=78, cv_issue_id=7800
    )
    ctx = import_ctx()
    await _add_series_grab(
        db, download_id="hum-2", series_id=strangelands.series_id,
        title="Strangelands Bundle",
    )

    outcomes = await _download(
        db, ctx, tmp_path / "hum2", "Daredevil 404 (1987).cbz", download_id="hum-2"
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].series_id == strangelands.series_id
    assert outcomes[0].issue_id == own_404
    assert outcomes[0].issue_id != daredevil.issue_id  # never the filename's series


@pytest.mark.req("FRG-PP-021")
async def test_underivable_issue_blocks_with_a_series_scoped_reason(
    db, seed, import_ctx, tmp_path
):
    """No issue number and no ordinal: the file blocks, but the reason names the
    series the grab established instead of claiming the series was unmatchable."""
    s = await seed(title="Strangelands", issue_number="8", cv_volume_id=77,
                   cv_issue_id=7700)
    ctx = import_ctx()
    await _add_series_grab(
        db, download_id="hum-3", series_id=s.series_id, title="Strangelands Bundle"
    )

    outcomes = await _download(
        db, ctx, tmp_path / "hum3", "Strangelands Collection.cbz", download_id="hum-3"
    )

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    reasons = outcomes[0].reasons
    assert any("Strangelands" in r and "issue number" in r for r in reasons)
    assert not any("known series and issue" in r for r in reasons)  # not the generic
    assert outcomes[0].series_id == s.series_id  # the block carries the series
    assert await _issue_files(db) == []
    async with db.read_session() as session:
        events = await history.all_events(session)
    assert events[0].event_type == "import_blocked"
    assert events[0].series_id == s.series_id


@pytest.mark.req("FRG-PP-021")
async def test_embedded_id_inside_the_provenance_series_still_resolves_the_issue(
    db, seed, import_ctx, tmp_path
):
    """The grab settled the SERIES, not the issue — so a verified embedded
    ComicVine id inside that series still corrects a mis-numbered file
    (FRG-IMP-024 keeps working for source-matched downloads)."""
    s = await seed(title="Strangelands", issue_number="8", cv_volume_id=77,
                   cv_issue_id=7700)
    id_9 = await _add_issue(db, s.series_id, cv_issue_id=7709, issue_number="9")
    ctx = import_ctx()
    await _add_series_grab(
        db, download_id="hum-7", series_id=s.series_id, title="Strangelands Bundle"
    )

    dl = tmp_path / "hum7"
    make_cbz_with_comicinfo(
        dl / "Some Other Name #8.cbz", xml=comicinfo_xml(cv_issue_id=7709)
    )
    outcomes = await _run(
        db, CompletedDownloadSource(download_id="hum-7", output_path=str(dl)), ctx
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].series_id == s.series_id
    assert outcomes[0].issue_id == id_9  # the embedded id, not the name's #8


@pytest.mark.req("FRG-PP-021")
async def test_embedded_id_outside_the_provenance_series_never_relocates_the_file(
    db, seed, import_ctx, tmp_path
):
    """An embedded id pointing at ANOTHER series is a conflict to surface, never
    a licence to move the file out of the series the operator matched."""
    s = await seed(title="Strangelands", issue_number="8", cv_volume_id=77,
                   cv_issue_id=7700)
    other = await seed(
        title="Daredevil", issue_number="404", cv_volume_id=78, cv_issue_id=7800
    )
    ctx = import_ctx()
    await _add_series_grab(
        db, download_id="hum-8", series_id=s.series_id, title="Strangelands Bundle"
    )

    dl = tmp_path / "hum8"
    make_cbz_with_comicinfo(
        dl / "Strangelands Collection.cbz", xml=comicinfo_xml(cv_issue_id=7800)
    )
    outcomes = await _run(
        db, CompletedDownloadSource(download_id="hum-8", output_path=str(dl)), ctx
    )

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    assert any("conflicts" in r for r in outcomes[0].reasons)
    assert outcomes[0].issue_id != other.issue_id
    assert await _issue_files(db) == []


# --- FRG-PP-022: ordinal fallback under a known series -----------------------


@pytest.mark.req("FRG-PP-022")
async def test_ordinal_lands_as_the_issue_when_the_known_series_holds_it(
    db, seed, import_ctx, tmp_path
):
    """"SPAWN Vol. 243" is a mislabeled single: the parser keeps it as
    ``volume_ordinal=243`` (issue None), and the pipeline resolves it to the
    provenance series' real #243."""
    s = await seed(title="SPAWN", issue_number="243", cv_volume_id=79,
                   cv_issue_id=7900)
    ctx = import_ctx()
    await _add_series_grab(
        db, download_id="hum-4", series_id=s.series_id, title="Spawn Origins Bundle"
    )

    outcomes = await _download(
        db, ctx, tmp_path / "hum4", "SPAWN Vol. 243.cbz", download_id="hum-4"
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].issue_id == s.issue_id


@pytest.mark.req("FRG-PP-022")
async def test_ordinal_miss_blocks_without_fabricating_an_issue(
    db, seed, import_ctx, tmp_path
):
    s = await seed(title="SPAWN", issue_number="243", cv_volume_id=79,
                   cv_issue_id=7900)
    ctx = import_ctx()
    await _add_series_grab(
        db, download_id="hum-5", series_id=s.series_id, title="Spawn Origins Bundle"
    )

    outcomes = await _download(
        db, ctx, tmp_path / "hum5", "SPAWN Vol. 9.cbz", download_id="hum-5"
    )

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    assert outcomes[0].issue_id is None
    assert any("SPAWN" in r and "issue number" in r for r in outcomes[0].reasons)
    assert await _issue_files(db) == []


@pytest.mark.req("FRG-PP-022")
async def test_present_issue_number_is_never_overridden_by_the_ordinal(
    db, seed, import_ctx, tmp_path
):
    """"Saga Vol. 2 #5" parses to issue 5 AND ordinal 2. The series holds #2 but
    not #5: the file must BLOCK on the issue it actually names — a present issue
    number is stronger evidence than a volume token and the ordinal is never
    consulted behind its back."""
    s = await seed(title="Saga", issue_number="2", cv_volume_id=80, cv_issue_id=8000)
    ctx = import_ctx()
    await _add_series_grab(
        db, download_id="hum-6", series_id=s.series_id, title="Saga Bundle"
    )

    outcomes = await _download(
        db, ctx, tmp_path / "hum6", "Saga Vol. 2 #5.cbz", download_id="hum-6"
    )

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    assert outcomes[0].issue_id is None  # NOT the ordinal's #2
    assert await _issue_files(db) == []


@pytest.mark.req("FRG-PP-022")
async def test_scoped_rescan_resolves_a_vol_file_via_the_ordinal(
    db, seed, import_ctx
):
    """A series-scoped rescan is the other explicitly-known-series context: a
    `Vol. 4` file sitting in the Saga folder lands on that series' #4."""
    s = await seed(title="Saga", issue_number="4", cv_volume_id=80, cv_issue_id=8000)
    make_cbz(s.series_path / "Saga Vol. 4.cbz")
    ctx = import_ctx()

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].issue_id == s.issue_id
