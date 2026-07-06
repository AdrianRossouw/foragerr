"""End-to-end pipeline: both sources, reconciliation, upgrade, history
(FRG-PP-001, FRG-PP-003, FRG-PP-005, FRG-PP-010, FRG-PP-011)."""

from __future__ import annotations

import datetime as dt
import inspect
from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.downloads.models import GrabHistoryRow
from foragerr.importer import history, pipeline
from foragerr.importer.pipeline import (
    ImportStatus,
    gather,
    import_candidate,
)
from foragerr.importer.sources import CompletedDownloadSource, RescanSource
from foragerr.library.models import IssueFileRow

from importer._archives import make_cbz


async def _add_grab(db, *, download_id, series_id, issue_id, title):
    async with db.write_session() as session:
        session.add(
            GrabHistoryRow(
                download_id=download_id,
                series_id=series_id,
                issue_id=issue_id,
                title=title,
                protocol="usenet",
                source="indexer",
                created_at=dt.datetime(2026, 7, 5),
            )
        )


async def _run(db, source, ctx):
    """gather → import_candidate for one source; returns the outcomes."""
    outcomes = []
    async with db.write_session() as session:
        for candidate in await gather(source, session, ctx):
            outcomes.append(await import_candidate(session, candidate, ctx))
    return outcomes


# --- FRG-PP-001: one pipeline, both sources ---------------------------------


@pytest.mark.req("FRG-PP-001")
async def test_completed_download_source_imports_and_records_history(
    db, seed, import_ctx, tmp_path
):
    s = await seed()
    ctx = import_ctx()
    dl_dir = tmp_path / "download" / "Batman.404"
    make_cbz(dl_dir / "Batman 404 (1987).cbz")
    await _add_grab(
        db, download_id="dl-1", series_id=s.series_id, issue_id=s.issue_id,
        title="Batman 404 (1987)",
    )
    source = CompletedDownloadSource(download_id="dl-1", output_path=str(dl_dir))

    outcomes = await _run(db, source, ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    async with db.read_session() as session:
        files = (await session.execute(select(IssueFileRow))).scalars().all()
        events = await history.events_for_issue(session, s.issue_id)
    assert len(files) == 1
    assert Path(files[0].path).name == "Batman 404 (1987) [__%d__].cbz" % s.issue_id
    assert Path(files[0].path).parent == s.series_path  # imported under the series
    assert [e.event_type for e in events] == ["imported"]


@pytest.mark.req("FRG-PP-001")
async def test_rescan_source_imports_via_same_stages(db, seed, import_ctx):
    s = await seed()
    # A correctly named file dropped into the series folder.
    make_cbz(s.series_path / "Batman 404 (1987).cbz")
    ctx = import_ctx()
    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)
    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    async with db.read_session() as session:
        files = (await session.execute(select(IssueFileRow))).scalars().all()
        events = await history.events_for_issue(session, s.issue_id)
    assert len(files) == 1
    assert events[0].source == history.SOURCE_RESCAN  # provenance recorded
    assert events[0].download_id is None  # rescan events carry no download


@pytest.mark.req("FRG-PP-001")
def test_single_decide_and_execute_implementation():
    """Audit: exactly one decide() and one execute(); source is data, not a fork."""
    from foragerr.importer import decisions

    # The pipeline uses the one decisions.decide — not a per-source copy.
    assert pipeline.decide is decisions.decide
    exec_defs = [
        name
        for name, obj in inspect.getmembers(pipeline, inspect.iscoroutinefunction)
        if name == "execute"
    ]
    assert exec_defs == ["execute"]
    # import_candidate calls the one decide() and the one execute() exactly once
    # each, and never branches them on the source kind (the source is data).
    src = inspect.getsource(pipeline.import_candidate)
    assert src.count("decide(") == 1
    assert src.count("execute(") == 1
    assert "source_kind ==" not in src and "source_kind !=" not in src


# --- FRG-PP-003: reconciliation ---------------------------------------------


@pytest.mark.req("FRG-PP-003")
async def test_download_id_match_survives_unparseable_name(db, seed, import_ctx):
    s = await seed()
    ctx = import_ctx()
    dl_dir = Path(ctx.config_dir).parent / "dl2"
    make_cbz(dl_dir / "x9f2_garbage_9931.cbz")  # unparseable file name
    await _add_grab(
        db, download_id="dl-2", series_id=s.series_id, issue_id=s.issue_id,
        title="unparseable too $$$",
    )
    source = CompletedDownloadSource(download_id="dl-2", output_path=str(dl_dir))
    outcomes = await _run(db, source, ctx)
    # Reconciled to the grabbed issue purely via the download-id join.
    assert outcomes[0].status is ImportStatus.IMPORTED
    assert outcomes[0].issue_id == s.issue_id


@pytest.mark.req("FRG-PP-003")
async def test_issue_id_tag_short_circuits_to_direct_lookup(db, seed, import_ctx):
    s = await seed()
    ctx = import_ctx()
    dl_dir = Path(ctx.config_dir).parent / "dl3"
    # No grab record; the embedded tag names our internal issue id directly.
    make_cbz(dl_dir / f"Whatever Title [__{s.issue_id}__].cbz")
    source = CompletedDownloadSource(download_id="dl-3", output_path=str(dl_dir))
    outcomes = await _run(db, source, ctx)
    assert outcomes[0].status is ImportStatus.IMPORTED
    assert outcomes[0].issue_id == s.issue_id


@pytest.mark.req("FRG-PP-003")
async def test_unresolvable_download_blocks_not_lost(db, seed, import_ctx):
    await seed()
    ctx = import_ctx()
    dl_dir = Path(ctx.config_dir).parent / "dl4"
    make_cbz(dl_dir / "Totally Unknown Series 001 (2099).cbz")
    source = CompletedDownloadSource(download_id="dl-4", output_path=str(dl_dir))
    outcomes = await _run(db, source, ctx)
    assert outcomes[0].status is ImportStatus.BLOCKED
    assert any("known series and issue" in r for r in outcomes[0].reasons)
    async with db.read_session() as session:
        events = await history.all_events(session)
        files = (await session.execute(select(IssueFileRow))).scalars().all()
    assert events[0].event_type == "import_blocked"  # persisted, not lost
    assert files == []  # nothing imported, source left in place
    assert Path(dl_dir / "Totally Unknown Series 001 (2099).cbz").exists()


# --- FRG-PP-008: remote path mapping ----------------------------------------


@pytest.mark.req("FRG-PP-008")
async def test_unmapped_remote_path_blocks_naming_the_fix(db, seed, import_ctx):
    await seed()
    ctx = import_ctx()
    # A Windows-shaped foreign path with no mapping configured.
    source = CompletedDownloadSource(
        download_id="dl-5", output_path=r"C:\downloads\Batman"
    )
    outcomes = await _run(db, source, ctx)
    assert outcomes[0].status is ImportStatus.BLOCKED
    assert any("remote-path mapping" in r for r in outcomes[0].reasons)


# --- FRG-PP-010: upgrade quarantines the replaced file ----------------------


@pytest.mark.req("FRG-PP-010")
@pytest.mark.req("FRG-PP-013")
async def test_upgrade_quarantines_replaced_file_and_swaps_row(db, seed, import_ctx, tmp_path):
    s = await seed()
    # M2: the replaced file goes to the configured recycle bin (FRG-PP-013); with
    # no bin it would be permanently deleted (covered in test_recycle_bin.py).
    recycle_bin = tmp_path / "recycle"
    recycle_bin.mkdir()
    ctx = import_ctx(recycle_bin_path=str(recycle_bin))
    # Existing lower-format file already imported for the issue.
    old = s.series_path / "Batman 404 old.cbr"
    old.write_bytes(b"old-cbr-file-contents-longer-than-floor" * 4)
    async with db.write_session() as session:
        from foragerr.library import repo

        await repo.add_issue_file(
            session, issue_id=s.issue_id, path=str(old), size=old.stat().st_size
        )

    dl_dir = Path(ctx.config_dir).parent / "up"
    make_cbz(dl_dir / "Batman 404 (1987).cbz")  # cbz outranks cbr → an upgrade
    await _add_grab(
        db, download_id="dl-up", series_id=s.series_id, issue_id=s.issue_id,
        title="Batman 404 (1987)",
    )
    source = CompletedDownloadSource(download_id="dl-up", output_path=str(dl_dir))
    outcomes = await _run(db, source, ctx)

    assert outcomes[0].status is ImportStatus.IMPORTED
    assert outcomes[0].upgraded
    async with db.read_session() as session:
        files = (await session.execute(select(IssueFileRow))).scalars().all()
        events = await history.events_for_issue(session, s.issue_id)
    # The issue_files row was swapped to the new file (old row gone).
    assert len(files) == 1
    assert files[0].path.endswith(".cbz")
    # The replaced file was recycled (moved, never deleted) and recorded.
    assert not old.exists()
    upgrade_event = events[-1]
    assert upgrade_event.event_type == "upgrade_replaced"
    assert upgrade_event.quarantine_path is not None
    assert Path(upgrade_event.quarantine_path).exists()
    assert recycle_bin in Path(upgrade_event.quarantine_path).parents


@pytest.mark.req("FRG-PP-013")
async def test_upgrade_without_bin_deletes_permanently_but_records_event(
    db, seed, import_ctx
):
    """No recycle bin configured (`recycle_bin_path=""`): the superseded file is
    permanently deleted, yet the upgrade is still recorded with no recycle path."""
    s = await seed()
    ctx = import_ctx()  # recycle_bin_path defaults to "" → permanent delete
    old = s.series_path / "Batman 404 old.cbr"
    old.write_bytes(b"old-cbr-file-contents-longer-than-floor" * 4)
    async with db.write_session() as session:
        from foragerr.library import repo

        await repo.add_issue_file(
            session, issue_id=s.issue_id, path=str(old), size=old.stat().st_size
        )

    dl_dir = Path(ctx.config_dir).parent / "up2"
    make_cbz(dl_dir / "Batman 404 (1987).cbz")
    await _add_grab(
        db, download_id="dl-up2", series_id=s.series_id, issue_id=s.issue_id,
        title="Batman 404 (1987)",
    )
    outcomes = await _run(
        db, CompletedDownloadSource(download_id="dl-up2", output_path=str(dl_dir)), ctx
    )

    assert outcomes[0].status is ImportStatus.IMPORTED
    assert outcomes[0].upgraded
    assert not old.exists()  # permanently deleted
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    upgrade_event = events[-1]
    assert upgrade_event.event_type == "upgrade_replaced"
    assert upgrade_event.quarantine_path is None  # no recycle path recorded
