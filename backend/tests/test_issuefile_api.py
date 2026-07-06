"""HTTP contract tests for the issue-file router (FRG-API-003, FRG-UI-004,
FRG-PP-013): DELETE /api/v1/issuefile/{id} rides the delete_issue_file flow —
recycle-bin routing, 404 mapping, the {recycled} response shape, and the
``source=manual`` provenance on the history event (a user action). Flow
ordering/compensation guarantees live in tests/importer/test_recycle_bin.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from foragerr.app import create_app
from foragerr.importer import history
from foragerr.library.models import IssueFileRow
from opds_support import opds_settings, seed, simple_series


@pytest.fixture
def bin_root(tmp_path: Path) -> Path:
    root = tmp_path / "recycle"
    root.mkdir()
    return root


@pytest.fixture
def client(tmp_path: Path, bin_root: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(opds_settings(cfg, recycle_bin_path=str(bin_root)))
    with TestClient(app) as c:
        yield c


def _seed_one_file(client, tmp_path) -> tuple[int, Path]:
    data = client.portal.call(
        seed, client.app, tmp_path / "library", [simple_series(n_issues=1)]
    )
    file_info = data["series"][0]["issues"][0]["files"][0]
    return file_info["id"], Path(file_info["path"])


async def _state(app) -> tuple[int, list]:
    async with app.state.db.read_session() as session:
        remaining = (await session.execute(select(IssueFileRow))).scalars().all()
        events = await history.all_events(session)
    return len(remaining), [
        e for e in events if e.event_type == history.EVENT_FILE_DELETED
    ]


@pytest.mark.req("FRG-API-003")
@pytest.mark.req("FRG-UI-004")
def test_delete_issue_file_routes_through_bin_and_records_manual_source(
    client, tmp_path, bin_root
):
    file_id, on_disk = _seed_one_file(client, tmp_path)

    response = client.delete(f"/api/v1/issuefile/{file_id}")

    assert response.status_code == 200
    recycled = response.json()["recycled"]
    assert recycled is not None
    assert bin_root in Path(recycled).parents  # response names the bin path
    assert not on_disk.exists()
    assert Path(recycled).read_bytes() == b"Saga-issue-1-bytes" * 4  # bytes intact

    remaining, deleted = client.portal.call(_state, client.app)
    assert remaining == 0  # row removed -> issue back to derived Wanted
    assert len(deleted) == 1
    assert deleted[0].source == "manual"  # a user action, never a rescan
    assert deleted[0].quarantine_path == recycled

    # The id is gone: a second delete is a 404, not a double-dispose.
    assert client.delete(f"/api/v1/issuefile/{file_id}").status_code == 404


@pytest.mark.req("FRG-API-003")
@pytest.mark.req("FRG-UI-004")
def test_delete_issue_file_without_bin_returns_null_recycled(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(opds_settings(cfg))  # no recycle bin configured
    with TestClient(app) as client:
        file_id, on_disk = _seed_one_file(client, tmp_path)

        response = client.delete(f"/api/v1/issuefile/{file_id}")

        assert response.status_code == 200
        assert response.json() == {"recycled": None}
        assert not on_disk.exists()  # permanently deleted
        remaining, deleted = client.portal.call(_state, client.app)
        assert remaining == 0
        assert len(deleted) == 1 and deleted[0].source == "manual"


@pytest.mark.req("FRG-API-003")
def test_delete_unknown_issue_file_is_404(client):
    response = client.delete("/api/v1/issuefile/999999")
    assert response.status_code == 404
    assert "999999" in response.json()["message"]
