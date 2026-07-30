"""The disposal-directory half of the read-only boundary (FRG-SER-021).

``recycle_bin_path`` / ``duplicate_dump_path`` are the one write surface that no
series-keyed or candidate-keyed guard can see: the series being deleted is
MANAGED and perfectly writable, and only the DESTINATION of the disposal lands
inside the operator's reference library. Every replaced or deleted file is moved
there, the bin root and its marker file are created there, and the retention
prune later ``rmtree``s dated folders there.

Rejecting the value at ``PUT /config/mediamanagement`` does not close it, so
both routes past that check are covered here:

* **ordering** — the directory is configured first and the root registered
  read-only afterwards, which the submission-time check never sees because it
  returns early while no read-only root exists (and ``POST /rootfolder`` does not
  look at the disposal settings);
* **not the API at all** — ``FORAGERR_RECYCLE_BIN_PATH`` / ``config.json``,
  reproduced by constructing ``Settings`` directly. A flag-only read-only root is
  writable on disk by construction, so the ``W_OK`` validator passes it.

Every read-only flag here is set on a writable temp directory, so a passing
assertion means foragerr chose not to write rather than the filesystem having
stopped it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import func, select

from foragerr.health.service import HealthService
from foragerr.importer import fileops, recycle
from foragerr.library import repo
from foragerr.library.flows import delete_issue_file, delete_series
from foragerr.library.models import IssueFileRow, IssueRow, RootFolderRow, SeriesRow
from foragerr.library.read_only import ReadOnlySeriesError

from http_support import make_settings
from read_only_support import snapshot

NOW = dt.datetime(2026, 7, 5, 12, 0, 0)


async def _managed_series_with_files(
    db, root_folder_id: int, format_profile_id: int, series_dir: Path, n: int
) -> tuple[int, list[Path]]:
    """A series on the ORDINARY writable root, with ``n`` files on disk."""
    series_dir.mkdir(parents=True, exist_ok=True)
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=7001,
            title="Example Series",
            start_year=2012,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=str(series_dir),
        )
        files: list[Path] = []
        for i in range(1, n + 1):
            issue = await repo.create_issue(
                session, series_id=series.id, cv_issue_id=i, issue_number=str(i)
            )
            path = series_dir / f"Example Series {i:03d}.cbz"
            path.write_bytes(f"example-series-issue-{i}-bytes".encode())
            await repo.add_issue_file(
                session, issue_id=issue.id, path=str(path), size=path.stat().st_size
            )
            files.append(path)
        return series.id, files


async def _register_read_only(db, path: Path) -> int:
    async with db.write_session() as session:
        row = await repo.create_root_folder(session, str(path), read_only=True)
        return row.id


async def _flag_read_only(db, root_folder_id: int) -> None:
    async with db.write_session() as session:
        (await session.get(RootFolderRow, root_folder_id)).read_only = True


async def _row_counts(db) -> tuple[int, int, int]:
    async with db.read_session() as session:
        return (
            await session.scalar(select(func.count()).select_from(SeriesRow)),
            await session.scalar(select(func.count()).select_from(IssueRow)),
            await session.scalar(select(func.count()).select_from(IssueFileRow)),
        )


def _reference_library(tmp_path: Path) -> tuple[Path, Path]:
    """A reference library holding one original file, plus the path a disposal
    directory would occupy INSIDE it."""
    reference = tmp_path / "reference-library"
    original = reference / "example series v1" / "Example Series 001 (2012).cbz"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"operator-original-bytes" * 8)
    return reference, reference / "recycle"


# --- route (a): the directory was configured BEFORE the root was flagged -----


@pytest.mark.req("FRG-SER-021")
async def test_a_bin_configured_before_the_root_was_flagged_refuses_the_delete(
    db, root_folder_id, root_folder_path, format_profile_id, tmp_path
):
    """The ordering bypass, on the subtle case: the SERIES is managed and
    writable, so every series-keyed guard answers "not read-only" — the delete is
    refused only because the bin it would move the files into is inside the
    reference library. Refused whole rather than degraded to a hard delete: a
    degrade turns a reversible move into permanent loss, which is the outcome
    FRG-PP-013's ordering discipline exists to prevent."""
    reference, bin_root = _reference_library(tmp_path)
    bin_root.mkdir()
    settings = make_settings(tmp_path / "cfg", recycle_bin_path=str(bin_root))
    # The submission-time check cannot fire in this order: the value is accepted
    # while no read-only root exists, and the root is registered afterwards.
    root_id = await _register_read_only(db, reference)
    series_id, files = await _managed_series_with_files(
        db, root_folder_id, format_profile_id, root_folder_path / "Example Series", 2
    )
    before = snapshot(reference)

    with pytest.raises(ReadOnlySeriesError) as refusal:
        await delete_series(db, series_id, delete_files=True, settings=settings)

    assert "recycle_bin_path" in str(refusal.value)
    assert snapshot(reference) == before
    assert all(path.exists() for path in files)  # the managed files survive too
    assert await _row_counts(db) == (1, 2, 2)
    assert root_id is not None


# --- route (b): the value never passed through the API ----------------------


@pytest.mark.req("FRG-SER-021")
async def test_a_bin_supplied_outside_the_api_refuses_a_single_file_delete(
    db, root_folder_id, root_folder_path, format_profile_id, tmp_path
):
    """``Settings`` built directly is the env-var / ``config.json`` route: the
    ``W_OK`` validator accepts the path because a flag-only read-only root is
    writable on disk, and no request ever reaches the config resource."""
    reference, bin_root = _reference_library(tmp_path)
    bin_root.mkdir()
    await _register_read_only(db, reference)
    settings = make_settings(tmp_path / "cfg", recycle_bin_path=str(bin_root))
    assert settings.recycle_bin_path == str(bin_root)  # accepted by validation
    series_id, files = await _managed_series_with_files(
        db, root_folder_id, format_profile_id, root_folder_path / "Example Series", 1
    )
    async with db.read_session() as session:
        file_id = await session.scalar(select(IssueFileRow.id))
    before = snapshot(reference)

    with pytest.raises(ReadOnlySeriesError) as refusal:
        await delete_issue_file(db, settings, file_id)

    assert "recycle_bin_path" in str(refusal.value)
    assert snapshot(reference) == before
    assert files[0].exists()
    assert await _row_counts(db) == (1, 1, 1)
    assert series_id is not None


@pytest.mark.req("FRG-SER-021")
async def test_a_bin_outside_every_reference_library_still_deletes(
    db, root_folder_id, root_folder_path, format_profile_id, tmp_path
):
    """The other side of the guard: a read-only root exists, but the bin is
    outside it, so ordinary recycling is untouched. Without this the refusal
    above could pass by breaking deletes generally."""
    reference, _unused = _reference_library(tmp_path)
    await _register_read_only(db, reference)
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()
    settings = make_settings(tmp_path / "cfg", recycle_bin_path=str(bin_root))
    series_id, files = await _managed_series_with_files(
        db, root_folder_id, format_profile_id, root_folder_path / "Example Series", 1
    )

    await delete_series(db, series_id, delete_files=True, settings=settings)

    assert not files[0].exists()
    assert len(list(bin_root.rglob("*.cbz"))) == 1
    assert await _row_counts(db) == (0, 0, 0)


# --- housekeeping: the sweep and the rmtree ---------------------------------


@pytest.mark.req("FRG-SER-021")
async def test_the_retention_prune_never_rmtrees_inside_a_reference_library(
    db, tmp_path
):
    """The most destructive reachable operation: ``prune_recycle_bin`` deletes
    whole dated folders under the configured bin. Given a fully prune-eligible
    layout INSIDE a reference library — the bin marker present and an aged
    ISO-date folder holding a file — it must refuse instead of removing it."""
    reference, bin_root = _reference_library(tmp_path)
    aged = bin_root / "2020-01-01"
    aged.mkdir(parents=True)
    (aged / "Example Series 002 (2012).cbz").write_bytes(b"aged-entry-bytes")
    (bin_root / fileops.RECYCLE_BIN_MARKER).touch()
    await _register_read_only(db, reference)
    before = snapshot(reference)

    with pytest.raises(ReadOnlySeriesError) as refusal:
        await recycle.prune_recycle_bin(db, str(bin_root), 1, now=NOW)

    assert "recycle_bin_path" in str(refusal.value)
    assert snapshot(reference) == before
    # ...and the same layout outside a reference library still prunes, so the
    # refusal above is the boundary rather than a broken prune.
    elsewhere = tmp_path / "recycle"
    (elsewhere / "2020-01-01").mkdir(parents=True)
    (elsewhere / "2020-01-01" / "aged.cbz").write_bytes(b"aged-entry-bytes")
    (elsewhere / fileops.RECYCLE_BIN_MARKER).touch()
    assert await recycle.prune_recycle_bin(db, str(elsewhere), 1, now=NOW) == 1


@pytest.mark.req("FRG-SER-021")
async def test_the_quarantine_sweep_never_moves_files_into_a_reference_library(
    db, tmp_path
):
    """The sweep MOVES leftover M1 quarantine files into the bin, so a bin
    inside a reference library makes housekeeping itself the write path."""
    reference, bin_root = _reference_library(tmp_path)
    config_dir = tmp_path / "cfg"
    stale = config_dir / "quarantine" / "2026-07-01" / "Example Series 003.cbz"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"leftover-quarantine-bytes")
    await _register_read_only(db, reference)
    before = snapshot(reference)

    with pytest.raises(ReadOnlySeriesError):
        await recycle.sweep_quarantine_to_recycle(
            db, config_dir=str(config_dir), recycle_bin_path=str(bin_root), now=NOW
        )

    assert snapshot(reference) == before
    assert stale.exists()  # nothing swept anywhere


# --- the validation-time safety net -----------------------------------------


@pytest.mark.req("FRG-SER-021")
async def test_health_reports_a_disposal_directory_inside_a_reference_library(
    db, tmp_path
):
    """The env-var route bypasses the API, so the misconfiguration has to be
    visible before the operator meets a refused delete. Reported per field, and
    absent entirely while both settings are outside every read-only root."""
    reference, bin_root = _reference_library(tmp_path)
    bin_root.mkdir()
    await _register_read_only(db, reference)

    clean = HealthService(
        db, make_settings(tmp_path / "cfg", recycle_bin_path=str(tmp_path / "recycle"))
    )
    assert await clean._disposal_path_components() == []

    broken = HealthService(
        db,
        make_settings(
            tmp_path / "cfg",
            recycle_bin_path=str(bin_root),
            duplicate_dump_path=str(reference / "dupes"),
        ),
    )
    components = await broken._disposal_path_components()

    assert [c.component for c in components] == [
        "disposal-path:recycle_bin_path",
        "disposal-path:duplicate_dump_path",
    ]
    assert all(c.state == "error" for c in components)
    assert all("recycle_bin_path" in (c.remediation or "") for c in components[:1])
    warnings = await broken.warnings()
    assert {"disposal-path:recycle_bin_path", "disposal-path:duplicate_dump_path"} <= {
        w.source for w in warnings
    }


# --- enumeration: no unguarded disposal call site ---------------------------

#: Every module allowed to call the ``fileops`` disposal primitives, and the
#: guard each one is behind. A new call site must join this table (and gain a
#: refusal test) before the suite is green again — the boundary is not a thing
#: anyone can be relied on to remember at a sixth call site.
_GUARDED_DISPOSAL_CALLERS = {
    "importer/pipeline.py": "refuse_read_only_disposal",
    "importer/recycle.py": "refuse_read_only_disposal",
    "library/flows/edit_delete.py": "refuse_read_only_disposal",
}

_DISPOSAL_PRIMITIVES = ("recycle_file", "dump_file", "prune_recycle_bin")


@pytest.mark.req("FRG-SER-021")
def test_every_disposal_call_site_consults_the_boundary():
    """The enumeration, mirroring the command-registry invariant: per-flow tests
    cannot notice a call site nobody thought to write a test for."""
    package = Path(fileops.__file__).parent.parent
    callers: dict[str, str] = {}
    for module in sorted(package.rglob("*.py")):
        relative = module.relative_to(package).as_posix()
        if relative == "importer/fileops.py":
            continue  # the primitives' own module
        text = module.read_text()
        if any(f"fileops.{name}" in text for name in _DISPOSAL_PRIMITIVES):
            callers[relative] = (
                "refuse_read_only_disposal"
                if "refuse_read_only_disposal" in text
                else "UNGUARDED"
            )
    assert callers == _GUARDED_DISPOSAL_CALLERS
