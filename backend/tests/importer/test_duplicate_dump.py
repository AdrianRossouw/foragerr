"""Duplicate constraint handling end to end (FRG-PP-014): the dump-folder
disposal of a duplicate resolution's losing file, its structural separation
from the recycle bin (never marked, never pruned), and the pipeline wiring —
tie replacement through ``execute``'s replaced-file branch, marker precedence
from real filenames, and the outcome/reason recorded in import history.
Decision-matrix unit coverage lives in ``test_decisions.py``; parser marker
rules in ``tests/parser/test_fix_markers.py``.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.downloads.models import GrabHistoryRow
from foragerr.importer import fileops, history
from foragerr.importer.pipeline import ImportStatus, gather, import_candidate
from foragerr.importer.sources import CompletedDownloadSource
from foragerr.library import repo
from foragerr.library.models import IssueFileRow

from importer._archives import make_cbz

NOW = dt.datetime(2026, 7, 5, 12, 0, 0)


# --- fileops.dump_file: dated subdirs, collisions, NOT a recycle bin ---------


@pytest.mark.req("FRG-PP-014")
def test_dump_file_moves_into_a_dated_subfolder(tmp_path):
    dump = tmp_path / "dupes"
    src = tmp_path / "Batman 404.cbz"
    src.write_bytes(b"payload")

    dest = fileops.dump_file(src, dump, now=NOW)

    assert dest == dump / "2026-07-05" / "Batman 404.cbz"
    assert dest.read_bytes() == b"payload"
    assert not src.exists()  # moved, not copied


@pytest.mark.req("FRG-PP-014")
def test_dump_file_never_overwrites_an_earlier_loser(tmp_path):
    """Collision-suffix mechanics shared with the recycle bin: a second loser
    with the same basename lands beside the first, never over it."""
    dump = tmp_path / "dupes"
    first = tmp_path / "a" / "Batman 404.cbz"
    second = tmp_path / "b" / "Batman 404.cbz"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    d1 = fileops.dump_file(first, dump, now=NOW)
    d2 = fileops.dump_file(second, dump, now=NOW)

    assert d1.name == "Batman 404.cbz"
    assert d2.name == "Batman 404.1.cbz"
    assert d1.read_bytes() == b"first"  # the earlier entry survives intact
    assert d2.read_bytes() == b"second"


@pytest.mark.req("FRG-PP-014")
def test_dump_root_is_never_marked_as_a_recycle_bin(tmp_path):
    dump = tmp_path / "dupes"
    src = tmp_path / "Batman 404.cbz"
    src.write_bytes(b"payload")

    fileops.dump_file(src, dump, now=NOW)

    assert not (dump / fileops.RECYCLE_BIN_MARKER).exists()


@pytest.mark.req("FRG-PP-014")
def test_recycle_prune_never_deletes_under_the_dump_root(tmp_path):
    """The structural guarantee: ``prune_recycle_bin`` requires the recycle-bin
    marker before deleting anything, and ``dump_file`` never writes one — so a
    retention prune pointed at the dump root (mis-wired or deliberate) removes
    nothing, even for entries far older than the retention window."""
    dump = tmp_path / "dupes"
    src = tmp_path / "Batman 404.cbz"
    src.write_bytes(b"payload")
    dest = fileops.dump_file(src, dump, now=dt.datetime(2020, 1, 1))

    removed = fileops.prune_recycle_bin(dump, 1, now=dt.datetime(2026, 7, 5))

    assert removed == 0
    assert dest.exists()  # the aged dump entry is untouched


# --- pipeline wiring: tie replacement, dump routing, history ----------------


async def _register_existing(db, issue_id: int, path: Path) -> None:
    async with db.write_session() as session:
        await repo.add_issue_file(
            session, issue_id=issue_id, path=str(path), size=path.stat().st_size
        )


async def _grab(db, *, download_id, series_id, issue_id, title):
    async with db.write_session() as session:
        session.add(
            GrabHistoryRow(
                download_id=download_id,
                series_id=series_id,
                issue_id=issue_id,
                title=title,
                protocol="usenet",
                source="indexer",
                created_at=NOW,
            )
        )


async def _run(db, source, ctx):
    outcomes = []
    async with db.write_session() as session:
        for candidate in await gather(source, session, ctx):
            outcomes.append(await import_candidate(session, candidate, ctx))
    return outcomes


async def _import_one(db, ctx, s, *, name: str, images: int, download_id: str):
    dl_dir = Path(ctx.config_dir).parent / f"dl-{download_id}"
    make_cbz(dl_dir / name, images=images)
    await _grab(
        db, download_id=download_id, series_id=s.series_id, issue_id=s.issue_id,
        title=Path(name).stem,
    )
    return await _run(
        db, CompletedDownloadSource(download_id=download_id, output_path=str(dl_dir)), ctx
    )


@pytest.mark.req("FRG-PP-014")
async def test_duplicate_loser_moves_to_the_dump_folder(db, seed, import_ctx, tmp_path):
    """A same-rung (cbz vs cbz) tie won on size sends the LOSING file to the
    dump folder's dated subfolder — not the recycle bin, and never deletion —
    and history records the replacement with the winning reason."""
    s = await seed()
    recycle = tmp_path / "recycle"
    dump = tmp_path / "dupes"
    recycle.mkdir()
    dump.mkdir()
    ctx = import_ctx(
        recycle_bin_path=str(recycle), duplicate_dump_path=str(dump)
    )
    old = s.series_path / "Batman 404 old.cbz"  # same rung as the incoming cbz
    make_cbz(old, images=1)
    await _register_existing(db, s.issue_id, old)

    outcomes = await _import_one(
        db, ctx, s, name="Batman 404 (1987).cbz", images=5, download_id="dup-1"
    )

    assert outcomes[0].status is ImportStatus.IMPORTED
    assert outcomes[0].upgraded  # a replacement, recorded as such
    assert not old.exists()
    dumped = Path(outcomes[0].quarantine_path)
    assert dump in dumped.parents  # went to the dump, NOT the recycle bin
    assert dumped.parent.name == "2026-07-05"  # dated subfolder
    assert recycle not in dumped.parents
    assert not (dump / fileops.RECYCLE_BIN_MARKER).exists()

    async with db.read_session() as session:
        files = (await session.execute(select(IssueFileRow))).scalars().all()
        events = await history.events_for_issue(session, s.issue_id)
    assert len(files) == 1 and files[0].path.endswith("Batman 404 (1987) [__%d__].cbz" % s.issue_id)
    replaced = events[-1]
    assert replaced.event_type == "upgrade_replaced"
    data = history.decode_data(replaced.data)
    assert "larger-size" in data["duplicate_reason"]  # outcome + reason visible


@pytest.mark.req("FRG-PP-014")
async def test_duplicate_without_dump_folder_uses_the_recycle_path_unchanged(
    db, seed, import_ctx, tmp_path
):
    """No dump folder configured: the existing replaced-file path applies — the
    duplicate's loser goes to the recycle bin exactly like an upgrade's."""
    s = await seed()
    recycle = tmp_path / "recycle"
    recycle.mkdir()
    ctx = import_ctx(recycle_bin_path=str(recycle))  # duplicate_dump_path=""
    old = s.series_path / "Batman 404 old.cbz"
    make_cbz(old, images=1)
    await _register_existing(db, s.issue_id, old)

    outcomes = await _import_one(
        db, ctx, s, name="Batman 404 (1987).cbz", images=5, download_id="dup-2"
    )

    assert outcomes[0].status is ImportStatus.IMPORTED
    assert recycle in Path(outcomes[0].quarantine_path).parents


@pytest.mark.req("FRG-PP-014")
async def test_profile_upgrade_keeps_the_recycle_path_even_with_a_dump_folder(
    db, seed, import_ctx, tmp_path
):
    """The dump folder is for duplicate resolutions ONLY: a genuine profile-order
    upgrade (cbr → cbz) still recycles its superseded file even when a dump
    folder is configured."""
    s = await seed()
    recycle = tmp_path / "recycle"
    dump = tmp_path / "dupes"
    recycle.mkdir()
    dump.mkdir()
    ctx = import_ctx(
        recycle_bin_path=str(recycle), duplicate_dump_path=str(dump)
    )
    old = s.series_path / "Batman 404 old.cbr"  # lower rung → upgrade
    old.write_bytes(b"old-cbr-file-contents-longer-than-floor" * 4)
    await _register_existing(db, s.issue_id, old)

    outcomes = await _import_one(
        db, ctx, s, name="Batman 404 (1987).cbz", images=1, download_id="up-1"
    )

    assert outcomes[0].status is ImportStatus.IMPORTED
    assert outcomes[0].upgraded
    recycled = Path(outcomes[0].quarantine_path)
    assert recycle in recycled.parents  # upgrade disposal unchanged
    assert dump not in recycled.parents
    assert list(dump.iterdir()) == []  # nothing dumped for an upgrade


@pytest.mark.req("FRG-PP-014")
async def test_not_larger_duplicate_is_blocked_with_the_reason_in_history(
    db, seed, import_ctx
):
    """The tie's rejection side: a same-rung file that is not larger is blocked
    (existing file untouched) and the constraint's reason lands in history."""
    s = await seed()
    ctx = import_ctx()
    old = s.series_path / "Batman 404 old.cbz"
    make_cbz(old, images=5)  # existing is the larger one
    await _register_existing(db, s.issue_id, old)

    outcomes = await _import_one(
        db, ctx, s, name="Batman 404 (1987).cbz", images=1, download_id="dup-3"
    )

    assert outcomes[0].status is ImportStatus.BLOCKED
    assert any("larger-size" in r for r in outcomes[0].reasons)
    assert old.exists()  # the existing file was never touched
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    blocked = events[-1]
    assert blocked.event_type == "import_blocked"
    assert any("larger-size" in r for r in history.decode_data(blocked.data)["reasons"])


@pytest.mark.req("FRG-PP-014")
async def test_fix_marker_from_real_filenames_wins_the_tie(db, seed, import_ctx, tmp_path):
    """End-to-end marker precedence: a smaller `(f1)` release replaces a larger
    unfixed existing file — the marker is parsed from the incoming filename and
    the existing file's stored basename, and the reason names the marker."""
    s = await seed()
    dump = tmp_path / "dupes"
    dump.mkdir()
    ctx = import_ctx(duplicate_dump_path=str(dump))
    old = s.series_path / "Batman 404 (1987).cbz"  # unfixed, larger
    make_cbz(old, images=5)
    await _register_existing(db, s.issue_id, old)

    outcomes = await _import_one(
        db, ctx, s, name="Batman 404 (1987) (f1).cbz", images=1, download_id="fix-1"
    )

    assert outcomes[0].status is ImportStatus.IMPORTED
    assert dump in Path(outcomes[0].quarantine_path).parents
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    data = history.decode_data(events[-1].data)
    assert "f1" in data["duplicate_reason"]


@pytest.mark.req("FRG-PP-014")
async def test_an_unfixed_incoming_file_never_beats_a_fixed_existing_one(
    db, seed, import_ctx
):
    """The existing file carries `(f2)` in its stored name: a larger unfixed
    incoming file is blocked, existing file untouched."""
    s = await seed()
    ctx = import_ctx()
    old = s.series_path / "Batman 404 (1987) (f2).cbz"
    make_cbz(old, images=1)
    await _register_existing(db, s.issue_id, old)

    outcomes = await _import_one(
        db, ctx, s, name="Batman 404 (1987).cbz", images=5, download_id="fix-2"
    )

    assert outcomes[0].status is ImportStatus.BLOCKED
    assert any("f2" in r and "fixed" in r for r in outcomes[0].reasons)
    assert old.exists()
