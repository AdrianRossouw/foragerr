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
    # Renaming is off by default now (FRG-PP-020): the completed download
    # imports under its own name, no identity tag stamped.
    assert Path(files[0].path).name == "Batman 404 (1987).cbz"
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


# --- FRG-PP-003: universal stale-tag guard (naming-defaults) -----------------


@pytest.mark.req("FRG-PP-003")
async def test_stale_tag_for_other_series_yields_to_filename_parse(
    db, seed, import_ctx
):
    """After a reinstall a `[__id__]` tag points at an arbitrary row. On an
    UNSCOPED import a parseable filename naming a different series must win over
    the stale tag — the file resolves to the series/issue the NAME identifies,
    never to whatever row the internal id now happens to hit."""
    batman = await seed(title="Batman", issue_number="404")
    daredevil = await seed(
        title="Daredevil", issue_number="404", cv_volume_id=99, cv_issue_id=8800
    )
    ctx = import_ctx()
    dl_dir = Path(ctx.config_dir).parent / "dl-stale"
    # Filename clearly parses to Daredevil #404; the tag names Batman's row (a
    # stale id from a previous database). Same issue number on both series, so
    # only the series-matching-key disagreement can catch it.
    make_cbz(dl_dir / f"Daredevil 404 (1987) [__{batman.issue_id}__].cbz")
    source = CompletedDownloadSource(download_id="dl-stale", output_path=str(dl_dir))
    outcomes = await _run(db, source, ctx)
    assert outcomes[0].status is ImportStatus.IMPORTED
    assert outcomes[0].issue_id == daredevil.issue_id  # resolved by the filename
    assert outcomes[0].issue_id != batman.issue_id  # NOT dragged into the tag's row


@pytest.mark.req("FRG-PP-003")
async def test_tag_only_unparseable_name_still_resolves_by_tag(db, seed, import_ctx):
    """A tag-only name (no parseable issue number — the legitimate DDL
    convention) carries nothing resolvable to disagree with, so the tag remains
    authoritative even though the leftover title text is not the series name.
    The universal guard must not regress this fall-through."""
    s = await seed(title="Batman", issue_number="404")
    ctx = import_ctx()
    dl_dir = Path(ctx.config_dir).parent / "dl-tagonly"
    # "Loose Pages Bundle" parses to a matching key but NO issue number; the tag
    # is the only resolvable signal.
    make_cbz(dl_dir / f"Loose Pages Bundle [__{s.issue_id}__].cbz")
    source = CompletedDownloadSource(download_id="dl-tagonly", output_path=str(dl_dir))
    outcomes = await _run(db, source, ctx)
    assert outcomes[0].status is ImportStatus.IMPORTED
    assert outcomes[0].issue_id == s.issue_id  # resolved by the tag


@pytest.mark.req("FRG-PP-003")
async def test_tag_agreeing_with_filename_short_circuits_to_base_tag(
    db, seed, import_ctx
):
    """When the tag and the filename parse AGREE (same series, same issue), the
    fast-path short-circuit to `_BASE_TAG` is preserved — the guard only fires on
    disagreement. Asserted at the base-resolution layer so the tag source, not a
    coincidental filename match, is what resolved the candidate."""
    from foragerr.importer.evidence import aggregate
    from foragerr.importer.pipeline import _BASE_TAG, _reconcile_base
    from foragerr.importer.sources import SOURCE_DOWNLOAD, ImportCandidate

    s = await seed(title="Batman", issue_number="404")
    ctx = import_ctx()
    file_name = f"Batman 404 (1987) [__{s.issue_id}__].cbz"
    evidence = aggregate(file_name=file_name, reference_year=2026)
    candidate = ImportCandidate(
        source_kind=SOURCE_DOWNLOAD,
        local_path=f"/downloads/{file_name}",
        size=1,
        file_name=file_name,
    )
    async with db.read_session() as session:
        series_id, issue_id, base_source = await _reconcile_base(
            session, candidate, evidence, ctx
        )
    assert base_source == _BASE_TAG  # fast-path, not the filename heuristic
    assert (series_id, issue_id) == (s.series_id, s.issue_id)


@pytest.mark.req("FRG-PP-003")
async def test_stale_tag_for_prefix_series_yields_to_filename_parse(
    db, seed, import_ctx
):
    """The guard uses EXACT series-key equality, not the loose-subset match:
    a filename naming a shorter series ("Batman") must not be treated as
    agreeing with a tag that points at a longer series sharing the prefix
    ("Batman Beyond"). Same issue number on both, so only the series check
    catches it — and the subset matcher would have wrongly agreed."""
    batman = await seed(title="Batman", issue_number="404")
    beyond = await seed(
        title="Batman Beyond", issue_number="404", cv_volume_id=97, cv_issue_id=8801
    )
    ctx = import_ctx()
    dl_dir = Path(ctx.config_dir).parent / "dl-prefix"
    make_cbz(dl_dir / f"Batman 404 (1987) [__{beyond.issue_id}__].cbz")
    source = CompletedDownloadSource(download_id="dl-prefix", output_path=str(dl_dir))
    outcomes = await _run(db, source, ctx)
    assert outcomes[0].status is ImportStatus.IMPORTED
    assert outcomes[0].issue_id == batman.issue_id  # the FILENAME's series wins
    assert outcomes[0].issue_id != beyond.issue_id  # not the stale tag's row


@pytest.mark.req("FRG-PP-003")
async def test_grab_title_cannot_mask_a_filename_disagreement(db, seed, import_ctx):
    """The guard is judged against the FILENAME layer, never the aggregated
    evidence (where a grab title outranks the filename). A grab title matching
    the stale tag must not let the tag survive a filename that names a different
    series. Asserted at the base-resolution layer: the tag is DISCARDED, so the
    result comes from grab-history (`_BASE_GRAB`), not the tag (`_BASE_TAG`) —
    proving the guard fired on the filename despite the grab-masked aggregate."""
    from foragerr.importer.evidence import LAYER_GRAB, aggregate
    from foragerr.importer.pipeline import _BASE_GRAB, _reconcile_base
    from foragerr.importer.sources import SOURCE_DOWNLOAD, ImportCandidate

    batman = await seed(title="Batman", issue_number="404")
    daredevil = await seed(
        title="Daredevil", issue_number="404", cv_volume_id=96, cv_issue_id=8802
    )
    ctx = import_ctx()
    # File names Daredevil but carries a stale Batman row-id tag; the grab title
    # agrees with the tag, so the AGGREGATE series is "batman" (grab outranks
    # filename) — the masking Codex flagged.
    file_name = f"Daredevil 404 (1987) [__{batman.issue_id}__].cbz"
    evidence = aggregate(
        grab_title="Batman 404 (1987)", file_name=file_name, reference_year=2026
    )
    assert evidence.provenance["series"] == LAYER_GRAB  # aggregate reads "batman"
    candidate = ImportCandidate(
        source_kind=SOURCE_DOWNLOAD,
        local_path=f"/downloads/{file_name}",
        size=1,
        file_name=file_name,
        grab_series_id=batman.series_id,
        grab_issue_id=batman.issue_id,
    )
    async with db.read_session() as session:
        series_id, issue_id, base_source = await _reconcile_base(
            session, candidate, evidence, ctx
        )
    assert base_source == _BASE_GRAB  # tag discarded; NOT _BASE_TAG
    assert issue_id == batman.issue_id  # from the download-id grab join
    assert daredevil.issue_id != batman.issue_id


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
