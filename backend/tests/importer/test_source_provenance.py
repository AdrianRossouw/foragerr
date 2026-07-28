"""Provenance-authoritative series resolution + the ordinal fallback
(FRG-PP-021, FRG-PP-022).

A store grab records the series the operator matched an entitlement to and NO
issue id (``GrabHistoryRow(source="store", series_id=…, issue_id=None)`` under a
``humble:<entitlement id>`` download id). These tests pin that such a grab fixes
the series — read from the entitlement's CURRENT match, so a re-match is honored
— that the filename is consulted for the ISSUE only, and that a `Vol. N` file
lands as issue N when, and only when, the known series really holds it AND all
three FRG-PP-022 guards pass.

The authority is store-gated: a series-only grab that is NOT a store grab (an
indexer force-grab) resolves by the pre-existing rules, so these fixtures build
the REAL store shape (source row + entitlement + `humble:` grab), never a
stand-in.
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
from foragerr.library.models import IssueFileRow, SeriesRow
from foragerr.sources.models import (
    MATCHED_VIA_AUTO,
    MATCHED_VIA_OPERATOR,
    SourceEntitlementRow,
    SourceRow,
)

from importer._archives import comicinfo_xml, make_cbz, make_cbz_with_comicinfo

_NOW = dt.datetime(2026, 7, 5)


async def _source_id(db) -> int:
    """One connected store source (the entitlements' FK parent)."""
    async with db.write_session() as session:
        existing = (await session.execute(select(SourceRow))).scalars().first()
        if existing is not None:
            return existing.id
        row = SourceRow(
            type="humble",
            name="Humble Bundle",
            settings="{}",
            connection_state="connected",
            auto_sync=False,
            added_at=_NOW,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _entitlement(
    db,
    *,
    series_id,
    matched_via=MATCHED_VIA_OPERATOR,
    human_name="Bundle Item",
    machine_name=None,
) -> int:
    """A matched store entitlement — the row the pipeline reads at import time."""
    source_id = await _source_id(db)
    async with db.write_session() as session:
        row = SourceEntitlementRow(
            source_id=source_id,
            gamekey="gk",
            machine_name=machine_name or human_name,
            human_name=human_name,
            classification="comic",
            review_status="matched",
            download_state="import_pending",
            matched_series_id=series_id,
            matched_via=matched_via,
            md5="a" * 32,
            filename="item.cbz",
            created_at=_NOW,
            updated_at=_NOW,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _store_grab(
    db,
    *,
    series_id,
    title,
    matched_via=MATCHED_VIA_OPERATOR,
    human_name="Bundle Item",
) -> str:
    """The REAL store-grab shape (``sources.grab``): an entitlement matched to a
    series plus its ``humble:<id>`` grab row carrying source ``store`` and no
    issue id. Returns the download id."""
    eid = await _entitlement(
        db, series_id=series_id, matched_via=matched_via, human_name=human_name
    )
    download_id = f"humble:{eid}"
    async with db.write_session() as session:
        session.add(
            GrabHistoryRow(
                download_id=download_id,
                series_id=series_id,
                issue_id=None,
                title=title,
                protocol="humble",
                source="store",
                created_at=_NOW,
            )
        )
    return download_id


async def _indexer_series_grab(db, *, download_id, series_id, title):
    """A NON-store series-only grab: the usenet force-grab shape (`POST /release`
    with a series but no issue). Carries no provenance authority."""
    async with db.write_session() as session:
        session.add(
            GrabHistoryRow(
                download_id=download_id,
                series_id=series_id,
                issue_id=None,
                title=title,
                protocol="usenet",
                source="dognzb",
                created_at=_NOW,
            )
        )


async def _rematch(db, entitlement_id: int, series_id: int | None) -> None:
    """Repoint an entitlement's match AFTER its grab (the re-match the operator
    makes between grab and import)."""
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        row.matched_series_id = series_id
        row.updated_at = _NOW


async def _series_booktype(db, series_id: int) -> str | None:
    async with db.read_session() as session:
        return (await session.get(SeriesRow, series_id)).booktype


async def _set_booktype(db, series_id: int, booktype: str | None) -> None:
    async with db.write_session() as session:
        (await session.get(SeriesRow, series_id)).booktype = booktype


async def _existing_file(db, issue_id: int, path: Path, *, size: int) -> int:
    """Register an on-disk file against an issue (the operator's existing copy)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    make_cbz(path)
    async with db.write_session() as session:
        row = IssueFileRow(
            issue_id=issue_id, path=str(path), size=size, added_at=_NOW
        )
        session.add(row)
        await session.flush()
        return row.id


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
    download_id = await _store_grab(
        db, series_id=s.series_id, title="Strangelands Bundle"
    )

    outcomes = await _download(
        db, ctx, tmp_path / "hum1", "Some Other Name #8.cbz", download_id=download_id
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
    download_id = await _store_grab(
        db, series_id=strangelands.series_id, title="Strangelands Bundle"
    )

    outcomes = await _download(
        db, ctx, tmp_path / "hum2", "Daredevil 404 (1987).cbz",
        download_id=download_id,
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
    download_id = await _store_grab(
        db, series_id=s.series_id, title="Strangelands Bundle"
    )

    outcomes = await _download(
        db, ctx, tmp_path / "hum3", "Strangelands Collection.cbz",
        download_id=download_id,
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
    download_id = await _store_grab(
        db, series_id=s.series_id, title="Strangelands Bundle"
    )

    dl = tmp_path / "hum7"
    make_cbz_with_comicinfo(
        dl / "Some Other Name #8.cbz", xml=comicinfo_xml(cv_issue_id=7709)
    )
    outcomes = await _run(
        db,
        CompletedDownloadSource(download_id=download_id, output_path=str(dl)),
        ctx,
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
    download_id = await _store_grab(
        db, series_id=s.series_id, title="Strangelands Bundle"
    )

    dl = tmp_path / "hum8"
    make_cbz_with_comicinfo(
        dl / "Strangelands Collection.cbz", xml=comicinfo_xml(cv_issue_id=7800)
    )
    outcomes = await _run(
        db,
        CompletedDownloadSource(download_id=download_id, output_path=str(dl)),
        ctx,
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
    download_id = await _store_grab(
        db, series_id=s.series_id, title="Spawn Origins Bundle"
    )

    outcomes = await _download(
        db, ctx, tmp_path / "hum4", "SPAWN Vol. 243.cbz", download_id=download_id
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
    download_id = await _store_grab(
        db, series_id=s.series_id, title="Spawn Origins Bundle"
    )

    outcomes = await _download(
        db, ctx, tmp_path / "hum5", "SPAWN Vol. 9.cbz", download_id=download_id
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
    download_id = await _store_grab(
        db, series_id=s.series_id, title="Saga Bundle"
    )

    outcomes = await _download(
        db, ctx, tmp_path / "hum6", "Saga Vol. 2 #5.cbz", download_id=download_id
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


# --- FRG-PP-021: the authority is store-gated and read at import time --------


@pytest.mark.req("FRG-PP-021")
async def test_non_store_series_only_grab_carries_no_authority(
    db, seed, import_ctx, tmp_path
):
    """A usenet force-grab (`POST /release`) writes the SAME series-set/issue-NULL
    shape a store grab does, with no operator match behind it. It must confer no
    authority: the file resolves by the pre-existing filename rules — so a name
    that parses cleanly to another in-library series lands THERE, exactly as it
    did before FRG-PP-021 existed."""
    strangelands = await seed(
        title="Strangelands", issue_number="8", cv_volume_id=77, cv_issue_id=7700
    )
    daredevil = await seed(
        title="Daredevil", issue_number="404", cv_volume_id=78, cv_issue_id=7800
    )
    ctx = import_ctx()
    # The force-grab's release title is the release name, as usenet grabs record
    # it — so the filename and grab layers agree and only the SERIES HINT (which
    # names Strangelands) could relocate the file. It must not.
    await _indexer_series_grab(
        db,
        download_id="nzb-1",
        series_id=strangelands.series_id,
        title="Daredevil 404 (1987)",
    )

    outcomes = await _download(
        db, ctx, tmp_path / "nzb1", "Daredevil 404 (1987).cbz", download_id="nzb-1"
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].series_id == daredevil.series_id  # the filename's series
    assert outcomes[0].issue_id == daredevil.issue_id


@pytest.mark.req("FRG-PP-022")
async def test_non_store_series_only_grab_gets_no_ordinal_fallback(
    db, seed, import_ctx, tmp_path
):
    """The ordinal fallback rides on the provenance authority, so the same
    force-grab shape never reaches it: "SPAWN Vol. 243" blocks with the generic
    unmatched reason (main's behaviour), never as SPAWN #243."""
    s = await seed(title="SPAWN", issue_number="243", cv_volume_id=79, cv_issue_id=7900)
    ctx = import_ctx()
    await _indexer_series_grab(
        db, download_id="nzb-2", series_id=s.series_id, title="Spawn"
    )

    outcomes = await _download(
        db, ctx, tmp_path / "nzb2", "SPAWN Vol. 243.cbz", download_id="nzb-2"
    )

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    assert outcomes[0].issue_id is None
    assert any("known series and issue" in r for r in outcomes[0].reasons)
    assert await _issue_files(db) == []


@pytest.mark.req("FRG-PP-021")
async def test_rematch_between_grab_and_import_is_honored(
    db, seed, import_ctx, tmp_path
):
    """The download was grabbed under a match to series A; the operator then
    re-matched the entitlement to series B. The import reads the CURRENT match,
    so the file lands in B — the grab row's stale series never decides."""
    a = await seed(title="Series A", issue_number="8", cv_volume_id=77, cv_issue_id=7700)
    b = await seed(title="Series B", issue_number="8", cv_volume_id=78, cv_issue_id=7800)
    ctx = import_ctx()
    download_id = await _store_grab(db, series_id=a.series_id, title="A Bundle")
    await _rematch(db, int(download_id.split(":")[1]), b.series_id)

    outcomes = await _download(
        db, ctx, tmp_path / "rem", "Unparseable Bundle Name #8.cbz",
        download_id=download_id,
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].series_id == b.series_id  # never the grab-time series A
    assert outcomes[0].issue_id == b.issue_id


@pytest.mark.req("FRG-PP-021")
async def test_dangling_matched_series_withdraws_the_authority(
    db, seed, import_ctx, tmp_path
):
    """The entitlement's match points at a series that no longer exists. The
    authority is withdrawn rather than exercised over a phantom: the file falls
    back to normal resolution and its reason never names the dead row id."""
    s = await seed(title="Strangelands", issue_number="8", cv_volume_id=77,
                   cv_issue_id=7700)
    ctx = import_ctx()
    download_id = await _store_grab(db, series_id=s.series_id, title="Strangelands")
    await _rematch(db, int(download_id.split(":")[1]), 999_999)  # deleted series

    outcomes = await _download(
        db, ctx, tmp_path / "dangle", "Unparseable Bundle Name.cbz",
        download_id=download_id,
    )

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    assert outcomes[0].series_id is None  # no phantom series on the block
    assert any("known series and issue" in r for r in outcomes[0].reasons)
    assert not any("999999" in r or "#999999" in r for r in outcomes[0].reasons)
    assert await _issue_files(db) == []


@pytest.mark.req("FRG-PP-021")
async def test_unmatched_entitlement_withdraws_the_authority(
    db, seed, import_ctx, tmp_path
):
    """An entitlement whose match was dropped (restore) confers nothing either —
    the same fall-back-to-normal-resolution path, so the filename decides."""
    daredevil = await seed(
        title="Daredevil", issue_number="404", cv_volume_id=78, cv_issue_id=7800
    )
    other = await seed(
        title="Strangelands", issue_number="8", cv_volume_id=77, cv_issue_id=7700
    )
    ctx = import_ctx()
    download_id = await _store_grab(
        db, series_id=other.series_id, title="Daredevil 404 (1987)"
    )
    await _rematch(db, int(download_id.split(":")[1]), None)

    outcomes = await _download(
        db, ctx, tmp_path / "unmatched", "Daredevil 404 (1987).cbz",
        download_id=download_id,
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].series_id == daredevil.series_id


# --- FRG-PP-022 guard 1: a trade never lands on a singles line ---------------


@pytest.mark.req("FRG-PP-022")
async def test_trade_cued_file_never_lands_on_a_singles_line_or_deletes_its_file(
    db, seed, import_ctx, tmp_path
):
    """The blocker this guard exists for: "Saga Vol 04 TPB.cbz" arriving for a
    SINGLE-issue Saga would otherwise file as issue #4 and — being larger than
    the operator's real single — win the duplicate-size contest and delete it.
    The guard refuses the ordinal outright: the candidate blocks and the
    existing file is untouched, on disk and in ``issue_files``."""
    s = await seed(title="Saga", issue_number="4", cv_volume_id=80, cv_issue_id=8000)
    assert (await _series_booktype(db, s.series_id)) is None  # a singles line
    existing_path = s.series_path / "Saga 004.cbz"
    existing_id = await _existing_file(db, s.issue_id, existing_path, size=10)
    ctx = import_ctx()
    download_id = await _store_grab(db, series_id=s.series_id, title="Saga Bundle")

    outcomes = await _download(
        db, ctx, tmp_path / "trade", "Saga Vol 04 TPB.cbz", download_id=download_id
    )

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    assert outcomes[0].issue_id is None
    assert any("collected edition" in r and "single-issue" in r
               for r in outcomes[0].reasons)
    # The operator's file is exactly as it was — no replacement, no recycle bin.
    assert existing_path.exists()
    files = await _issue_files(db)
    assert [(f.id, f.path, f.size) for f in files] == [
        (existing_id, str(existing_path), 10)
    ]


@pytest.mark.req("FRG-PP-022")
async def test_trade_guard_also_covers_a_scoped_rescan(db, seed, import_ctx):
    """The guard is a property of the inference, not of the store path: a trade
    file rescanned inside a singles series' own folder is refused identically."""
    s = await seed(title="Saga", issue_number="4", cv_volume_id=80, cv_issue_id=8000)
    ctx = import_ctx()
    make_cbz(s.series_path / "Saga Vol 04 TPB.cbz")

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    assert any("collected edition" in r for r in outcomes[0].reasons)
    assert await _issue_files(db) == []


@pytest.mark.req("FRG-PP-022")
async def test_true_trade_lands_in_its_collected_edition_series(
    db, seed, import_ctx, tmp_path
):
    """The other half of the guard: when the target series IS collected-edition
    typed, "Saga Vol. 4" is exactly what it says it is and lands as its #4."""
    s = await seed(title="Saga", issue_number="4", cv_volume_id=80, cv_issue_id=8000)
    await _set_booktype(db, s.series_id, "tpb")
    ctx = import_ctx()
    download_id = await _store_grab(db, series_id=s.series_id, title="Saga Bundle")

    outcomes = await _download(
        db, ctx, tmp_path / "tpb", "Saga Vol 04 TPB.cbz", download_id=download_id
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].issue_id == s.issue_id


# --- FRG-PP-022 guard 2: an ordinal mapping never replaces a file -----------


@pytest.mark.req("FRG-PP-022")
async def test_ordinal_lands_on_an_empty_slot_but_blocks_on_an_occupied_one(
    db, seed, import_ctx, tmp_path
):
    """Both halves of guard 2 over ONE store download: #243 has no file, so the
    ordinal resolves it and the file imports; #244 already has one, so its
    candidate blocks for manual confirmation instead of entering the duplicate
    contest — and that existing file is left exactly as it was."""
    s = await seed(title="SPAWN", issue_number="243", cv_volume_id=79, cv_issue_id=7900)
    id_244 = await _add_issue(db, s.series_id, cv_issue_id=7944, issue_number="244")
    occupied = s.series_path / "SPAWN 244.cbz"
    occupied_id = await _existing_file(db, id_244, occupied, size=10)
    ctx = import_ctx()
    download_id = await _store_grab(db, series_id=s.series_id, title="Spawn Bundle")

    dl = tmp_path / "spawn"
    make_cbz(dl / "SPAWN Vol. 243.cbz")
    make_cbz(dl / "SPAWN Vol. 244.cbz")
    outcomes = await _run(
        db,
        CompletedDownloadSource(download_id=download_id, output_path=str(dl)),
        ctx,
    )

    by_name = {o.candidate.file_name: o for o in outcomes}
    assert by_name["SPAWN Vol. 243.cbz"].status is ImportStatus.IMPORTED
    assert by_name["SPAWN Vol. 243.cbz"].issue_id == s.issue_id
    blocked = by_name["SPAWN Vol. 244.cbz"]
    assert blocked.status is ImportStatus.BLOCKED
    assert blocked.issue_id is None
    assert any("already has a file" in r for r in blocked.reasons)
    assert not any("not larger than" in r for r in blocked.reasons)  # never arbitrated
    assert occupied.exists()
    files = {f.id: (f.issue_id, f.path, f.size) for f in await _issue_files(db)}
    assert files[occupied_id] == (id_244, str(occupied), 10)


@pytest.mark.req("FRG-PP-022")
async def test_existing_file_guard_also_covers_a_scoped_rescan(
    db, seed, import_ctx
):
    """Guard 2 in the rescan path: a `Vol. 4` file found in the folder of a
    collected-edition series whose #4 already has a file blocks rather than
    arbitrating against it."""
    s = await seed(title="Saga", issue_number="4", cv_volume_id=80, cv_issue_id=8000)
    await _set_booktype(db, s.series_id, "tpb")
    existing_path = s.series_path / "Saga Vol 04 (2013).cbz"
    await _existing_file(db, s.issue_id, existing_path, size=10)
    ctx = import_ctx()
    make_cbz(s.series_path / "Saga Vol. 4 (alt).cbz")

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    assert any("already has a file" in r for r in outcomes[0].reasons)
    assert existing_path.exists()
    assert len(await _issue_files(db)) == 1


# --- FRG-PP-022 guard 3: only an operator-made match unlocks the fallback ----


@pytest.mark.req("FRG-PP-022")
async def test_auto_matched_entitlement_never_uses_the_ordinal_fallback(
    db, seed, import_ctx, tmp_path
):
    """Auto-sync matched this entitlement (a bare "Vol. N" title clears the 0.85
    threshold easily), so no human chose the series the fallback's safety
    argument rests on: the file blocks for review. The SAME file under an
    operator-made match imports."""
    s = await seed(title="SPAWN", issue_number="243", cv_volume_id=79, cv_issue_id=7900)
    ctx = import_ctx()
    auto_id = await _store_grab(
        db, series_id=s.series_id, title="Spawn Bundle",
        matched_via=MATCHED_VIA_AUTO, human_name="auto item",
    )

    auto = await _download(
        db, ctx, tmp_path / "auto", "SPAWN Vol. 243.cbz", download_id=auto_id
    )

    assert [o.status for o in auto] == [ImportStatus.BLOCKED]
    assert auto[0].issue_id is None
    assert any("automatically" in r for r in auto[0].reasons)
    assert await _issue_files(db) == []

    operator_id = await _store_grab(
        db, series_id=s.series_id, title="Spawn Bundle",
        matched_via=MATCHED_VIA_OPERATOR, human_name="operator item",
    )
    operator = await _download(
        db, ctx, tmp_path / "op", "SPAWN Vol. 243.cbz", download_id=operator_id
    )

    assert [o.status for o in operator] == [ImportStatus.IMPORTED]
    assert operator[0].issue_id == s.issue_id


@pytest.mark.req("FRG-PP-022")
async def test_match_predating_provenance_tracking_withholds_the_fallback(
    db, seed, import_ctx, tmp_path
):
    """A legacy row (``matched_via`` NULL — a match made before the column
    existed, when auto-sync could produce one indistinguishably) is not proof of
    a human choice, so the fallback stays withheld: pre-change behaviour, with a
    reason that says exactly that rather than blaming auto-sync."""
    s = await seed(title="SPAWN", issue_number="243", cv_volume_id=79, cv_issue_id=7900)
    ctx = import_ctx()
    download_id = await _store_grab(
        db, series_id=s.series_id, title="Spawn Bundle", matched_via=None
    )

    outcomes = await _download(
        db, ctx, tmp_path / "legacy", "SPAWN Vol. 243.cbz", download_id=download_id
    )

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    assert outcomes[0].issue_id is None
    assert any("not recorded" in r for r in outcomes[0].reasons)
    assert not any("automatically" in r for r in outcomes[0].reasons)
    assert await _issue_files(db) == []


@pytest.mark.req("FRG-PP-022")
async def test_guard_3_never_touches_a_real_issue_number(
    db, seed, import_ctx, tmp_path
):
    """The guards bound the ORDINAL fallback alone. An auto-matched entitlement
    whose file names a real issue still imports — the direct issue match is not
    an inference and is never withheld."""
    s = await seed(title="SPAWN", issue_number="243", cv_volume_id=79, cv_issue_id=7900)
    ctx = import_ctx()
    download_id = await _store_grab(
        db, series_id=s.series_id, title="Spawn Bundle", matched_via=MATCHED_VIA_AUTO
    )

    outcomes = await _download(
        db, ctx, tmp_path / "auto-issue", "Some Bundle Name #243.cbz",
        download_id=download_id,
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].issue_id == s.issue_id
