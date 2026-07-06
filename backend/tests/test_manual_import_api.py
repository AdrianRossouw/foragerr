"""Manual-import endpoints (FRG-API-015).

Listing under a path or a blocked download, execute-by-command, and the typed
error shape — exercised over the real app through ``TestClient`` next to the
other top-level API tests.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.db import utcnow
from foragerr.downloads.models import TrackedDownloadRow
from foragerr.library import repo
from foragerr.library.paths import series_folder_name

from http_support import make_settings
from importer._archives import make_cbz, make_cbz_with_comicinfo, comicinfo_xml


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


async def _seed(app, root: Path) -> dict:
    """Create a library root + Batman #404 (cv 9001); return the ids + root."""
    root.mkdir(parents=True, exist_ok=True)
    folder = root / series_folder_name("Batman", 1987)
    folder.mkdir(parents=True, exist_ok=True)
    db = app.state.db
    async with db.write_session() as session:
        root_row = await repo.create_root_folder(session, str(root))
        series = await repo.create_series(
            session, cv_volume_id=42, title="Batman", start_year=1987,
            format_profile_id=1, root_folder_id=root_row.id, path=str(folder),
        )
        issue = await repo.create_issue(
            session, series_id=series.id, cv_issue_id=9001,
            issue_number="404", issue_type="regular",
        )
    return {"series_id": series.id, "issue_id": issue.id, "root": str(root)}


async def _seed_blocked_download(app, staging: Path, download_id: str) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    now = utcnow()
    async with app.state.db.write_session() as session:
        session.add(
            TrackedDownloadRow(
                download_id=download_id,
                client_id=None,
                state="import_blocked",
                status="warning",
                title="Some Release",
                output_path=str(staging),
                added_at=now,
                updated_at=now,
            )
        )


@pytest.mark.req("FRG-API-015")
def test_list_candidates_for_a_path(client, tmp_path):
    seeded = client.portal.call(_seed, client.app, tmp_path / "library")
    inbox = Path(seeded["root"]) / "inbox"
    # Above the real 100 KiB junk-size floor so the verified match approves.
    make_cbz_with_comicinfo(
        inbox / "unknown-release.cbz",
        xml=comicinfo_xml(cv_issue_id=9001),
        filler_bytes=150 * 1024,
    )

    resp = client.get("/api/v1/manual-import", params={"path": str(inbox)})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    entry = body[0]
    assert entry["name"] == "unknown-release.cbz"
    assert entry["size"] > 0
    assert set(entry) >= {
        "path", "name", "size", "folder", "approved", "rejections",
        "suggestedSeriesId", "suggestedIssueId", "format", "embedded",
    }
    # Embedded ComicInfo summary is reported (IMP-024 read); the CV id resolves
    # so the verified embedded id maps it to the seeded issue.
    assert entry["embedded"]["comicInfoPresent"] is True
    assert entry["embedded"]["cvIssueId"] == 9001
    assert entry["embedded"]["verified"] is True
    assert entry["approved"] is True
    assert entry["suggestedIssueId"] == seeded["issue_id"]


@pytest.mark.req("FRG-API-015")
def test_list_candidates_for_a_blocked_download(client, tmp_path):
    client.portal.call(_seed, client.app, tmp_path / "library")
    staging = tmp_path / "staging" / "Some.Release"
    make_cbz(staging / "unknown-release.cbz")
    client.portal.call(_seed_blocked_download, client.app, staging, "dl-42")

    resp = client.get("/api/v1/manual-import", params={"downloadId": "dl-42"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    # No grab record / no filename match → blocked with a visible reason.
    assert body[0]["approved"] is False
    assert body[0]["rejections"]


@pytest.mark.req("FRG-API-015")
def test_submit_corrected_mappings_enqueues_a_command(client, tmp_path):
    seeded = client.portal.call(_seed, client.app, tmp_path / "library")
    inbox = Path(seeded["root"]) / "inbox"
    picked = inbox / "unknown-release.cbz"
    make_cbz(picked)

    resp = client.post(
        "/api/v1/manual-import",
        json={
            "files": [
                {
                    "path": str(picked),
                    "seriesId": seeded["series_id"],
                    "issueId": seeded["issue_id"],
                }
            ]
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "manual-import"
    assert body["status"] in {"queued", "started", "completed"}


@pytest.mark.req("FRG-API-015")
def test_unknown_download_is_a_typed_error(client, tmp_path):
    client.portal.call(_seed, client.app, tmp_path / "library")
    resp = client.get("/api/v1/manual-import", params={"downloadId": "nope"})
    assert resp.status_code == 404
    body = resp.json()
    assert "message" in body and "errors" in body


@pytest.mark.req("FRG-API-015")
def test_unreadable_path_is_a_typed_error(client, tmp_path):
    client.portal.call(_seed, client.app, tmp_path / "library")
    resp = client.get(
        "/api/v1/manual-import", params={"path": str(tmp_path / "does-not-exist")}
    )
    assert resp.status_code in {400, 404}
    body = resp.json()
    assert "message" in body and "errors" in body


@pytest.mark.req("FRG-API-015")
def test_post_path_outside_managed_roots_is_rejected(client, tmp_path):
    seeded = client.portal.call(_seed, client.app, tmp_path / "library")
    stray = tmp_path / "elsewhere" / "x.cbz"
    make_cbz(stray)
    resp = client.post(
        "/api/v1/manual-import",
        json={
            "files": [
                {
                    "path": str(stray),
                    "seriesId": seeded["series_id"],
                    "issueId": seeded["issue_id"],
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert "errors" in resp.json()
