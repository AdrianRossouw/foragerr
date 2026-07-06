"""Read-only root-folder + format-profile list endpoints (FRG-SER-008,
FRG-QUAL-001, FRG-UI-005).

These two GET collections back the add-series screen's Root Folder and Format
Profile pickers (FRG-UI-005), so it can offer real choices instead of raw id
inputs. FRG-QUAL-001 (the format-profile entity) is the id the list serves; the
add-flow need (FRG-UI-005) is why it exists as an endpoint. Both are plain
arrays (the sets are tiny) rather than the paging envelope.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from foragerr.app import create_app
from foragerr.library import repo
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow
from http_support import make_settings


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return make_settings(cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


async def _create_root_folder(app, path: str) -> int:
    async with app.state.db.write_session() as session:
        row = await repo.create_root_folder(session, path)
        return row.id


async def _create_series_under_root(app, root_folder_id: int, path: str) -> int:
    """Persist a minimal series row referencing ``root_folder_id`` (the delete
    guard's precondition) — bypasses the add flow (no ComicVine call)."""
    async with app.state.db.write_session() as session:
        default_profile_id = await session.scalar(
            select(FormatProfileRow.id).where(
                FormatProfileRow.name == DEFAULT_PROFILE_NAME
            )
        )
        row = await repo.create_series(
            session,
            cv_volume_id=4050 + root_folder_id,
            title="Guarded Series",
            format_profile_id=default_profile_id,
            root_folder_id=root_folder_id,
            path=path,
        )
        return row.id


# --- root folders ------------------------------------------------------------


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_list_is_empty_before_any_are_configured(client):
    resp = client.get("/api/v1/rootfolder")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_list_returns_configured_folders_with_free_space(client, tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    rid = client.portal.call(_create_root_folder, client.app, str(root))

    rows = client.get("/api/v1/rootfolder").json()
    assert len(rows) == 1
    assert rows[0]["id"] == rid
    assert rows[0]["path"] == str(root)
    # A real, existing path reports a non-negative free-space figure.
    assert isinstance(rows[0]["free_space"], int)
    assert rows[0]["free_space"] >= 0


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_free_space_is_none_for_a_missing_path(client, tmp_path):
    missing = tmp_path / "gone"  # never created
    client.portal.call(_create_root_folder, client.app, str(missing))
    rows = client.get("/api/v1/rootfolder").json()
    assert rows[0]["free_space"] is None  # stat failure must not fail the list


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_free_space_is_read_off_the_event_loop(client, tmp_path, monkeypatch):
    """The blocking ``disk_usage`` stat runs in the thread pool, not on the
    event loop — a hung network mount must not freeze the whole server."""
    import threading

    from foragerr.api import library_config

    root = tmp_path / "library"
    root.mkdir()
    client.portal.call(_create_root_folder, client.app, str(root))

    seen: dict = {}
    real_offload = library_config.run_in_threadpool

    async def recording_offload(func, *args, **kwargs):
        seen["func"] = func  # the callable handed to the thread pool
        seen["loop_thread"] = threading.current_thread()  # awaited on the loop

        def wrapped(*a, **k):
            seen["exec_thread"] = threading.current_thread()  # ran in the pool
            return func(*a, **k)

        return await real_offload(wrapped, *args, **kwargs)

    monkeypatch.setattr(library_config, "run_in_threadpool", recording_offload)

    rows = client.get("/api/v1/rootfolder").json()
    assert rows[0]["free_space"] >= 0
    # The stat was offloaded (disk_usage), and it executed on a DIFFERENT thread
    # than the one awaiting it (the event loop) — i.e. off the loop.
    assert getattr(seen.get("func"), "__name__", "") == "disk_usage"
    assert seen["exec_thread"] is not seen["loop_thread"]


# --- root-folder registration (POST) -----------------------------------------


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_post_registers_an_absolute_writable_directory(client, tmp_path):
    root = tmp_path / "library"
    root.mkdir()

    resp = client.post("/api/v1/rootfolder", json={"path": str(root)})
    assert resp.status_code == 201
    body = resp.json()
    assert body["path"] == str(root)
    assert body["id"] >= 1
    assert isinstance(body["free_space"], int) and body["free_space"] >= 0

    # It is immediately listed.
    listed = client.get("/api/v1/rootfolder").json()
    assert [r["path"] for r in listed] == [str(root)]


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_post_rejects_a_relative_path(client):
    resp = client.post("/api/v1/rootfolder", json={"path": "relative/library"})
    assert resp.status_code == 400
    assert resp.json()["errors"] == [
        {"field": "path", "message": "path 'relative/library' must be absolute"}
    ]


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_post_rejects_a_missing_directory(client, tmp_path):
    missing = tmp_path / "gone"  # never created
    resp = client.post("/api/v1/rootfolder", json={"path": str(missing)})
    assert resp.status_code == 400
    err = resp.json()["errors"][0]
    assert err["field"] == "path"
    assert "is not an existing directory" in err["message"]


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_post_rejects_an_unwritable_directory(client, tmp_path):
    root = tmp_path / "readonly"
    root.mkdir(mode=0o500)
    try:
        resp = client.post("/api/v1/rootfolder", json={"path": str(root)})
        assert resp.status_code == 400
        err = resp.json()["errors"][0]
        assert err["field"] == "path"
        assert "is not writable" in err["message"]
    finally:
        root.chmod(0o700)  # let pytest's tmp_path cleanup remove it


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_post_rejects_a_duplicate(client, tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    assert client.post("/api/v1/rootfolder", json={"path": str(root)}).status_code == 201

    resp = client.post("/api/v1/rootfolder", json={"path": str(root)})
    assert resp.status_code == 400
    assert "already registered" in resp.json()["errors"][0]["message"]


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_post_rejects_a_path_nested_under_an_existing_root(client, tmp_path):
    parent = tmp_path / "library"
    child = parent / "marvel"
    child.mkdir(parents=True)
    assert client.post("/api/v1/rootfolder", json={"path": str(parent)}).status_code == 201

    resp = client.post("/api/v1/rootfolder", json={"path": str(child)})
    assert resp.status_code == 400
    err = resp.json()["errors"][0]
    assert err["field"] == "path"
    assert "inside an existing root folder" in err["message"]


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_post_rejects_a_path_containing_an_existing_root(client, tmp_path):
    parent = tmp_path / "library"
    child = parent / "marvel"
    child.mkdir(parents=True)
    assert client.post("/api/v1/rootfolder", json={"path": str(child)}).status_code == 201

    resp = client.post("/api/v1/rootfolder", json={"path": str(parent)})
    assert resp.status_code == 400
    err = resp.json()["errors"][0]
    assert err["field"] == "path"
    assert "contains an existing root folder" in err["message"]


# --- root-folder removal (DELETE) --------------------------------------------


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_delete_unknown_id_is_404(client):
    resp = client.delete("/api/v1/rootfolder/999")
    assert resp.status_code == 404


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_delete_removes_an_unreferenced_root_leaving_files(client, tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    keeper = root / "keep.cbz"
    keeper.write_bytes(b"comic")
    rid = client.post("/api/v1/rootfolder", json={"path": str(root)}).json()["id"]

    resp = client.delete(f"/api/v1/rootfolder/{rid}")
    assert resp.status_code == 204
    assert client.get("/api/v1/rootfolder").json() == []
    # Files on disk are untouched — only the row was removed.
    assert keeper.exists()
    assert root.exists()


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_delete_refuses_while_a_series_references_it(client, tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    rid = client.post("/api/v1/rootfolder", json={"path": str(root)}).json()["id"]
    client.portal.call(
        _create_series_under_root, client.app, rid, str(root / "Guarded Series (2020)")
    )

    resp = client.delete(f"/api/v1/rootfolder/{rid}")
    assert resp.status_code == 409
    assert "1 series" in resp.json()["message"]
    # It is still registered — the refusal changed nothing.
    assert len(client.get("/api/v1/rootfolder").json()) == 1


# --- format profiles ---------------------------------------------------------


@pytest.mark.req("FRG-QUAL-001")
@pytest.mark.req("FRG-UI-005")
def test_formatprofile_list_includes_the_seeded_default(client):
    resp = client.get("/api/v1/formatprofile")
    assert resp.status_code == 200
    rows = resp.json()
    default = next(r for r in rows if r["name"] == DEFAULT_PROFILE_NAME)
    assert default["id"] >= 1
    # Ordered ladder + cutoff surface verbatim for the picker.
    assert default["formats"] == ["pdf", "cbr", "cbz"]
    assert default["cutoff"] == "cbz"
