"""LibraryImportSource intake + in-place registration edges (FRG-IMP-023,
FRG-IMP-024) — gate-review pins for the existing-library import seams:

- gather skips already-registered files, so a partial re-run never blocks an
  imported file against itself;
- ``library_import_mode`` gates ONLY library-import candidates — a rescan with
  renaming disabled still places nested files at their computed destination;
- physical-file (samefile) comparisons, never raw strings: a symlinked walk
  path must not dispose of the very file it registers;
- the series-only override preserves ch2's embedded-id precedence: a verified
  in-scope embedded ComicVine id wins the issue mapping, a conflicting one
  blocks for review.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.importer import history
from foragerr.importer.pipeline import ImportStatus, gather, import_candidate
from foragerr.importer.sources import LibraryImportSource, RescanSource
from foragerr.library import repo
from foragerr.library.models import IssueFileRow

from importer._archives import comicinfo_xml, make_cbz, make_cbz_with_comicinfo


async def _run(db, source, ctx):
    outcomes = []
    async with db.write_session() as session:
        for candidate in await gather(source, session, ctx):
            outcomes.append(await import_candidate(session, candidate, ctx))
    return outcomes


async def _issue_files(db):
    async with db.read_session() as session:
        rows = (await session.execute(select(IssueFileRow))).scalars().all()
        for r in rows:
            session.expunge(r)
        return rows


async def _add_issue(db, series_id, *, cv_issue_id, issue_number):
    async with db.write_session() as session:
        issue = await repo.create_issue(
            session,
            series_id=series_id,
            cv_issue_id=cv_issue_id,
            issue_number=issue_number,
        )
        return issue.id


# --- gather: a partial re-run only re-candidates unregistered files ----------


@pytest.mark.req("FRG-IMP-023")
async def test_partial_rerun_gathers_only_unregistered_files(db, seed, import_ctx):
    """Re-running a partially-imported group must skip files already linked to
    an issue-file record (the RescanSource pattern) — never re-candidate an
    imported file so it blocks against itself."""
    s = await seed()
    await _add_issue(db, s.series_id, cv_issue_id=9002, issue_number="405")
    f404 = s.series_path / "Batman 404 (1987).cbz"
    f405 = s.series_path / "Batman 405 (1987).cbz"
    make_cbz(f404)
    make_cbz(f405)
    # f404 was registered by an earlier (partial) run.
    async with db.write_session() as session:
        await repo.add_issue_file(
            session, issue_id=s.issue_id, path=str(f404), size=f404.stat().st_size
        )
    ctx = import_ctx()
    source = LibraryImportSource(
        series_id=s.series_id, files=(str(f404), str(f405))
    )

    async with db.read_session() as session:
        candidates = await gather(source, session, ctx)

    assert [c.local_path for c in candidates] == [str(f405)]


# --- library_import_mode gates ONLY library-import candidates -----------------


@pytest.mark.req("FRG-IMP-023")
@pytest.mark.req("FRG-SER-010")
async def test_rescan_with_rename_disabled_still_places_nested_files(
    db, seed, import_ctx
):
    """``library_import_mode`` is per-run context data, but it must only reach
    library-import candidates: a rescan candidate nested under the series
    folder with renaming disabled still routes through place_file to its
    computed destination — exactly as before the mode existed — instead of
    being silently registered in place."""
    s = await seed()
    nested = s.series_path / "nested" / "Batman 404 (1987).cbz"
    make_cbz(nested)
    ctx = import_ctx(rename_enabled=False)  # library_import_mode stays "in_place"

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    dest = s.series_path / "Batman 404 (1987).cbz"
    assert outcomes[0].imported_path == str(dest)
    assert dest.exists() and not nested.exists()  # moved, not registered nested


# --- physical-file comparison: a symlinked walk path is the same file --------


@pytest.mark.req("FRG-IMP-023")
async def test_symlinked_walk_path_never_disposes_of_the_registered_file(
    db, seed, import_ctx, tmp_path
):
    """The tracked existing row (series.path string) and the in-place candidate
    (symlinked walk path) name the SAME physical file. The import must swap the
    row's path in place — with no recycle bin configured, the pre-fix raw-string
    comparison would have permanently DELETED the file it just registered."""
    s = await seed()
    real = s.series_path / "Batman 404 (1987).cbz"
    make_cbz(real, images=5)
    real_size = real.stat().st_size
    # Tracked under the REAL path with a stale smaller recorded size, so the
    # same-rung candidate wins the larger-size duplicate tie and reaches execute.
    async with db.write_session() as session:
        await repo.add_issue_file(
            session, issue_id=s.issue_id, path=str(real), size=100
        )
    walked = tmp_path / "walked"
    walked.mkdir()
    link_dir = walked / "Batman (1987)"
    link_dir.symlink_to(s.series_path, target_is_directory=True)
    aliased = link_dir / "Batman 404 (1987).cbz"
    ctx = import_ctx(rename_enabled=False)  # no recycle bin, no dump configured

    outcomes = await _run(
        db, LibraryImportSource(series_id=s.series_id, files=(str(aliased),)), ctx
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert real.exists()  # the just-registered file was NOT disposed of
    assert real.stat().st_size == real_size
    assert outcomes[0].quarantine_path is None  # nothing recycled/dumped
    files = await _issue_files(db)
    assert len(files) == 1  # the stale row was replaced, not duplicated
    assert Path(files[0].path) == aliased  # row path swapped in place
    assert files[0].size == real_size


# --- series-only override keeps ch2's embedded-id precedence ------------------


@pytest.mark.req("FRG-IMP-023")
@pytest.mark.req("FRG-IMP-024")
async def test_pinned_series_still_honours_a_verified_embedded_id(
    db, seed, import_ctx
):
    """A mis-numbered file whose embedded ComicVine id names a real issue INSIDE
    the confirmed series imports as the embedded issue, not the filename's —
    the series-only override must not bypass the embedded layer."""
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    id_405 = await _add_issue(db, s.series_id, cv_issue_id=9002, issue_number="405")
    # Mis-numbered on disk (the filename parses to 405); embedded id says 404.
    path = s.series_path / "Batman 405 (1987).cbz"
    make_cbz_with_comicinfo(path, xml=comicinfo_xml(cv_issue_id=9001))
    ctx = import_ctx(rename_enabled=False)

    outcomes = await _run(
        db, LibraryImportSource(series_id=s.series_id, files=(str(path),)), ctx
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].issue_id == s.issue_id  # the embedded issue won
    assert outcomes[0].issue_id != id_405
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    data = history.decode_data(events[-1].data)
    assert data["provenance"]["issue"] == "comicinfo"  # verified, ch2 semantics


@pytest.mark.req("FRG-IMP-023")
@pytest.mark.req("FRG-IMP-024")
async def test_pinned_series_blocks_a_conflicting_embedded_id(db, seed, import_ctx):
    """An embedded id resolving OUTSIDE the confirmed series never silently
    wins and never silently loses: the conflict is recorded so
    EmbeddedIdConflictSpec blocks the file for review (FRG-IMP-024)."""
    batman = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    await seed(
        title="Superman", issue_number="1", cv_volume_id=100, cv_issue_id=8001
    )
    path = batman.series_path / "Batman 404 (1987).cbz"
    # Filename matches the pinned series' issue, but the embedded id points at
    # a Superman issue — a conflict the pin must not paper over.
    make_cbz_with_comicinfo(path, xml=comicinfo_xml(cv_issue_id=8001))
    ctx = import_ctx(rename_enabled=False)

    outcomes = await _run(
        db, LibraryImportSource(series_id=batman.series_id, files=(str(path),)), ctx
    )

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    assert any("conflicts" in r for r in outcomes[0].reasons)
    assert await _issue_files(db) == []  # never silently mis-filed
