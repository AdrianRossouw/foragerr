"""The registry-level read-only invariant for file-mutating commands
(FRG-SER-021).

``POST /api/v1/command`` enqueues any registered command by name, so an
API-layer refusal is bypassable by construction and every file-mutating command
has to hold the boundary itself. That was applied selectively — four commands
reached a mutation through the generic enqueue route unguarded — and no per-flow
test could notice, because a command nobody wrote a test for has no test to fail.

So this file does not test commands one by one. It ENUMERATES the registry's
file-mutation exclusivity group, requires a table entry per member, and drives
every one of them at a read-only reference library. A new file-mutating command
fails the enumeration until it is added here, and an unguarded one fails the
zero-write assertion.

The read-only flag is set on a perfectly writable temp directory, so a passing
assertion means foragerr chose not to write rather than the filesystem having
stopped it.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.db import CommandRow, utcnow
from foragerr.importer import IMPORT_FILE_MUTATION_GROUP
from foragerr.library.flows.library_import import encode_group_files
from foragerr.library.models import LibraryImportGroupRow, RootFolderRow

from opds_support import opds_settings, seed, simple_series
from read_only_support import commands_in_group, snapshot

#: The ComicVine volume id the seeded reference series is created with, echoed
#: onto the staged import group so ``library-import`` resolves to that series.
_CV_VOLUME_ID = 4242

#: How to aim each file-mutating command at the read-only reference library.
#: A callable taking the seeded ``Target`` and returning the command payload.
#: Keyed by command name so the enumeration below can assert completeness — the
#: whole point of the table.
#:
#: Commands that name a DESTINATION are aimed at the reference series itself;
#: the two that name a SOURCE separately from their destination are aimed at the
#: reference library's files with the MANAGED series as the destination, which is
#: the shape that makes every root-key guard answer "writable" while the files
#: being moved are the operator's originals.
_PAYLOAD_BUILDERS = {
    # No target of its own: it drains whatever completed downloads exist. It is
    # in the table so a future payload cannot be added without a test.
    "process-imports": lambda t: {},
    "manual-import": lambda t: {
        "files": [{"path": str(t.stray_path), "series_id": t.managed_series_id}]
    },
    "library-import": lambda t: {"group_ids": [t.group_id]},
    "rename-series": lambda t: {"series_id": t.series_id},
    "delete-series-files": lambda t: {"series_id": t.series_id},
    "rescan-series": lambda t: {
        "series_id": t.managed_series_id,
        "path_override": str(t.root_path),
    },
    "convert-series": lambda t: {"series_id": t.series_id},
    "convert-issue": lambda t: {"issue_id": t.issue_id},
}


class Target:
    """The read-only reference library every command in the table is aimed at,
    plus a MANAGED series on a writable root to serve as a destination."""

    def __init__(
        self,
        *,
        root_id: int,
        root_path: Path,
        series_id: int,
        issue_id: int,
        file_path: Path,
        stray_path: Path,
        group_id: int,
        managed_series_id: int,
    ) -> None:
        self.root_id = root_id
        self.root_path = root_path
        self.series_id = series_id
        self.issue_id = issue_id
        self.file_path = file_path
        #: An UNTRACKED archive inside the reference library, named so it parses
        #: to the managed series' only issue. Untracked matters: a file already
        #: carrying an ``issue_files`` row is refused by the already-imported
        #: spec, which would make the source-side cases pass for a reason that
        #: has nothing to do with this boundary.
        self.stray_path = stray_path
        self.group_id = group_id
        self.managed_series_id = managed_series_id


@pytest.fixture
def client(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(opds_settings(cfg))
    with TestClient(app) as c:
        yield c


async def _prepare(app, root_path: Path) -> Target:
    """Seed a library under ``root_path``, flip its root read-only, stage a
    confirmed import group over its files, and add a managed series on a
    separate writable root to act as a destination."""
    managed = await seed(
        app,
        root_path.parent / "managed-library",
        [simple_series(title="Managed Series", cv_volume_id=5150, n_issues=1)],
    )
    data = await seed(
        app,
        root_path,
        [
            simple_series(
                title="Example Series", cv_volume_id=_CV_VOLUME_ID, n_issues=1
            )
        ],
    )
    series = data["series"][0]
    file_path = Path(series["issues"][0]["files"][0]["path"])
    stray_path = _make_cbz(root_path / "loose" / "Managed Series 001 (2012).cbz")
    async with app.state.db.write_session() as session:
        (await session.get(RootFolderRow, data["root_id"])).read_only = True
        group = LibraryImportGroupRow(
            matching_key="example series",
            root_folder_id=data["root_id"],
            folder=str(file_path.parent),
            files=encode_group_files([(str(file_path), file_path.stat().st_size)]),
            confidence=1.0,
            state="confirmed",
            confirmed_cv_volume_id=_CV_VOLUME_ID,
            scanned_at=utcnow(),
        )
        session.add(group)
        await session.flush()
        group_id = group.id
    return Target(
        root_id=data["root_id"],
        root_path=root_path,
        series_id=series["id"],
        issue_id=series["issues"][0]["id"],
        file_path=file_path,
        stray_path=stray_path,
        group_id=group_id,
        managed_series_id=managed["series"][0]["id"],
    )


_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f9f0000000049454e44ae42"
    "6082"
)


def _make_cbz(path: Path, *, filler: int = 200 * 1024) -> Path:
    """A valid cbz (>=1 image entry) clearing the junk-size floor, so the
    pipeline's own safety specs cannot be what refuses it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("page000.png", _PNG_1x1)
        zf.writestr("filler.bin", os.urandom(filler))
    return path


async def _await_terminal(app, command_id: int) -> str:
    from conftest import eventually

    async def _done() -> str | None:
        async with app.state.db.read_session() as session:
            row = await session.get(CommandRow, command_id)
            if row is None or row.status not in ("completed", "failed"):
                return None
            return row.status

    return await eventually(_done)


@pytest.mark.req("FRG-SER-021")
def test_every_file_mutating_command_is_aimed_at_the_boundary(client):
    """The enumeration itself. A command that mutates library files carries the
    import file-mutation exclusivity group, so the group IS the list of commands
    the boundary must cover — and a new one has to arrive with a payload that
    targets a read-only series before this suite is green again."""
    assert commands_in_group(IMPORT_FILE_MUTATION_GROUP) == set(_PAYLOAD_BUILDERS)


@pytest.mark.req("FRG-SER-021")
@pytest.mark.parametrize("command_name", sorted(_PAYLOAD_BUILDERS))
def test_a_file_mutating_command_writes_nothing_to_a_reference_library(
    client, tmp_path, command_name
):
    """Driven through the GENERIC enqueue route, not the command's own endpoint:
    that is the route the API-layer refusals do not cover, and the one the
    bypasses were reachable through. Whatever the command's terminal status, the
    reference library must come out byte-identical."""
    target = client.portal.call(_prepare, client.app, tmp_path / "reference-library")
    before = snapshot(target.root_path)
    payload = _PAYLOAD_BUILDERS[command_name](target)

    enqueued = client.post(
        "/api/v1/command", json={"name": command_name, "payload": payload}
    )

    if enqueued.status_code == 409:
        # Refused up front for the 409 UX; nothing was queued, nothing ran.
        assert "read-only reference library" in enqueued.json()["message"]
    else:
        assert enqueued.status_code == 201, enqueued.text
        client.portal.call(_await_terminal, client.app, enqueued.json()["id"])
    assert snapshot(target.root_path) == before


@pytest.mark.req("FRG-SER-021")
def test_the_table_targets_the_reference_library_rather_than_a_stub(client, tmp_path):
    """Guards the guard: a payload that quietly stopped naming the read-only
    series (a renamed field, a stale id) would make every case above pass
    vacuously. Asserted by checking that the seeded target really is the
    read-only one and that its file really is inside the root."""
    target = client.portal.call(_prepare, client.app, tmp_path / "reference-library")

    resource = client.get(f"/api/v1/series/{target.series_id}").json()
    assert resource["read_only"] is True
    assert target.file_path.is_relative_to(target.root_path)
    assert target.file_path.exists()
