"""HTTP contract for the file-mutating read-only surfaces (FRG-SER-021).

The write boundary has to hold on the routes that reach a file mutation WITHOUT
going through the import pipeline's placement step, and on the two configuration
routes that can aim a write INTO a reference library:

* ``POST /api/v1/convert/{series,issue}`` and the same commands enqueued
  directly through ``POST /api/v1/command`` — conversion writes a new archive
  and deletes the source, and it never calls ``pipeline.execute``;
* ``GET``/``POST /api/v1/manual-import`` — source confinement is "any managed
  root", which includes a read-only one, so a reference library reads as a
  legitimate place to import files OUT of;
* ``PUT /api/v1/config/mediamanagement`` — the disposal directories are moved
  into and pruned from;
* ``POST /api/v1/rootfolder`` — a second registration of the same physical
  directory with the opposite flag would hand out write access to the files the
  flag protects.

Every refusal of an OPERATION answers the uniform 409 with the ``read_only``
field discriminator; the two configuration routes reject a submitted VALUE, so
they answer the field-precise 400 their own contract already uses.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.api import library_config
from foragerr.app import create_app
from foragerr.library import repo
from foragerr.library.models import RootFolderRow
from opds_support import opds_settings, seed, simple_series


@pytest.fixture
def client(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(opds_settings(cfg))
    with TestClient(app) as c:
        yield c


async def _mark_root_read_only(app, root_id: int) -> None:
    async with app.state.db.write_session() as session:
        (await session.get(RootFolderRow, root_id)).read_only = True


async def _add_read_only_root(app, path: Path) -> int:
    async with app.state.db.write_session() as session:
        row = await repo.create_root_folder(session, str(path), read_only=True)
        return row.id


def _seed_reference_library(client, tmp_path: Path) -> dict:
    """One seeded series whose root is then flipped read-only."""
    data = client.portal.call(
        seed,
        client.app,
        tmp_path / "reference-library",
        [simple_series(title="Example Series", n_issues=1)],
    )
    client.portal.call(_mark_root_read_only, client.app, data["root_id"])
    return data


def _assert_read_only_refusal(response) -> None:
    """The shared refusal contract: 409, the uniform error shape, and the
    structural ``read_only`` discriminator the UI classifies on."""
    assert response.status_code == 409, response.text
    body = response.json()
    assert set(body) == {"message", "errors"}
    assert "read-only reference library" in body["message"]
    assert [e["field"] for e in body["errors"]] == ["read_only"]


# --- on-demand conversion (FRG-PP-018 surfaces) ------------------------------


@pytest.mark.req("FRG-SER-021")
def test_convert_endpoints_refuse_a_read_only_series(client, tmp_path):
    data = _seed_reference_library(client, tmp_path)
    series_id = data["series"][0]["id"]
    issue_id = data["series"][0]["issues"][0]["id"]

    _assert_read_only_refusal(
        client.post("/api/v1/convert/series", json={"seriesId": series_id})
    )
    _assert_read_only_refusal(
        client.post("/api/v1/convert/issue", json={"issueId": issue_id})
    )


@pytest.mark.req("FRG-SER-021")
def test_convert_commands_refuse_a_read_only_series_when_enqueued_directly(
    client, tmp_path
):
    """``POST /api/v1/command`` can enqueue any registered command by name, so
    an API-layer-only refusal is bypassable by construction. The flow itself
    refuses, which is what makes the boundary hold for background execution —
    asserted here through the generic enqueue route the endpoints share nothing
    with."""
    data = _seed_reference_library(client, tmp_path)
    series_id = data["series"][0]["id"]
    issue_id = data["series"][0]["issues"][0]["id"]

    for name, payload in (
        ("convert-series", {"series_id": series_id}),
        ("convert-issue", {"issue_id": issue_id}),
    ):
        enqueued = client.post(
            "/api/v1/command", json={"name": name, "payload": payload}
        )
        assert enqueued.status_code == 201, enqueued.text
        command_id = enqueued.json()["id"]
        record = client.portal.call(_await_command, client.app, command_id)
        assert record["status"] == "failed"
        assert "read-only reference library" in (record["error"] or "")


async def _await_command(app, command_id: int) -> dict:
    from conftest import eventually
    from foragerr.db import CommandRow

    async def _terminal() -> dict | None:
        async with app.state.db.read_session() as session:
            row = await session.get(CommandRow, command_id)
            if row is None or row.status not in ("completed", "failed"):
                return None
            return {"status": row.status, "error": row.error}

    return await eventually(_terminal)


# --- manual import (FRG-API-015 surface) -------------------------------------


@pytest.mark.req("FRG-SER-021")
def test_manual_import_refuses_a_reference_library_as_a_source(client, tmp_path):
    """Manual import confines picks to "any managed library root", and a
    read-only root IS one — so the reference library was both LISTED as an
    import source and importable out of, with the destination series' own
    (writable) root passing every guard. Refused on the SOURCE path, at the
    listing as well as at the pick, so it is never offered in the first place."""
    reference = tmp_path / "reference-library"
    original = reference / "example series v1" / "Example Series 001 (2012).cbz"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"example-series-issue-1-bytes" * 8)
    client.portal.call(_add_read_only_root, client.app, reference)
    before = original.stat()

    listed = client.get("/api/v1/manual-import", params={"path": str(original.parent)})
    picked = client.post(
        "/api/v1/manual-import", json={"files": [{"path": str(original)}]}
    )

    assert listed.status_code == 409, listed.text
    assert "read-only reference library" in listed.json()["message"]
    _assert_read_only_refusal(picked)
    assert original.exists()
    assert original.stat().st_ino == before.st_ino
    assert original.stat().st_mtime_ns == before.st_mtime_ns


# --- configuration routes ----------------------------------------------------


@pytest.mark.req("FRG-SER-021")
def test_disposal_paths_cannot_point_inside_a_reference_library(client, tmp_path):
    """Every replaced or deleted file is MOVED into the recycle bin / duplicate
    dump, and housekeeping later DELETES from them. Pointed inside a reference
    library, the two configuration fields turn the whole boundary into a write
    path, so each is rejected against its own field."""
    reference = tmp_path / "reference-library"
    reference.mkdir()
    client.portal.call(_add_read_only_root, client.app, reference)
    current = client.get("/api/v1/config/mediamanagement").json()

    for field in ("recycle_bin_path", "duplicate_dump_path"):
        response = client.put(
            "/api/v1/config/mediamanagement",
            json={**current, field: str(reference / "bin")},
        )
        assert response.status_code == 400, response.text
        body = response.json()
        assert "read-only reference library" in body["message"]
        assert [e["field"] for e in body["errors"]] == [f"settings.{field}"]

    # Unchanged: neither value was persisted.
    assert client.get("/api/v1/config/mediamanagement").json() == current


@pytest.mark.req("FRG-SER-021")
@pytest.mark.req("FRG-SER-008")
def test_the_same_directory_cannot_register_twice_under_a_different_spelling(
    client, tmp_path, monkeypatch
):
    """On a case-insensitive volume ``<root>`` and ``<Root>`` are the SAME
    directory, so a read-only root re-registered under a different case would
    hand out write access to the very files the flag protects — the duplicate
    and nesting checks compared realpath STRINGS, which do not case-fold.

    The duplicate check now asks the filesystem (device+inode), which also
    catches a bind mount or hard-linked directory. The case-insensitive overlap
    is reproduced with the probe forced on over two directories whose names
    differ only in case — physically distinct on a case-sensitive test volume,
    which is exactly the pair a case-insensitive volume collapses into one."""
    reference = tmp_path / "Reference"
    reference.mkdir()
    client.portal.call(_add_read_only_root, client.app, reference)

    # Same physical directory, spelled through a symlink.
    linked = tmp_path / "reference-link"
    os.symlink(reference, linked)
    duplicate = client.post("/api/v1/rootfolder", json={"path": str(linked)})
    assert duplicate.status_code == 400
    assert "already registered" in duplicate.json()["message"]
    # ...and the same-directory test is what answers, not the string compare:
    # these two spellings differ as strings and name one directory. A volume
    # that preserves case while resolving it case-insensitively puts ``<root>``
    # and ``<Root>`` in exactly this position.
    assert str(linked) != str(reference)
    assert library_config._same_directory(str(linked), str(reference)) is True

    # The probe reports the truth about the test volume; the folded comparison
    # is then exercised by forcing it.
    assert library_config._case_insensitive_filesystem(str(reference)) is False
    monkeypatch.setattr(library_config, "_case_insensitive_filesystem", lambda _p: True)

    other_case = tmp_path / "REFERENCE"
    (other_case / "inner").mkdir(parents=True)
    for candidate in (other_case, other_case / "inner"):
        overlap = client.post("/api/v1/rootfolder", json={"path": str(candidate)})
        assert overlap.status_code == 400, overlap.text
        assert "existing root folder" in overlap.json()["message"]
