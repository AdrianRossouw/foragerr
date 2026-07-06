"""Typed config resource endpoints: GET/PUT naming + media management (FRG-API-013).

Placed at the top level next to the other API tests (``test_library_config_api.py``);
the api-spec's suggested ``tests/api/`` path is the same coverage under a different
folder.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.api.config_resources import MediaManagementConfig, NamingConfig
from foragerr.app import create_app
from foragerr.config import Settings
from foragerr.library import repo
from foragerr.library.paths import series_folder_name
from http_support import make_settings

_ROUNDTRIP_TEMPLATE = "{Series Title} {Issue Number:0000} ({Year}) [__{IssueId}__]"


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


async def _seed_series_with_file(app, root: Path) -> int:
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
        wrong = folder / "wrong scan.cbz"
        wrong.write_bytes(b"comic" * 1024)
        await repo.add_issue_file(
            session, issue_id=issue.id, path=str(wrong), size=wrong.stat().st_size
        )
        return series.id


@pytest.mark.req("FRG-API-013")
def test_get_naming_returns_typed_current_values(client):
    resp = client.get("/api/v1/config/naming")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "rename_enabled",
        "file_naming_template",
        "folder_naming_template",
        "replace_illegal_characters",
    }
    assert isinstance(body["file_naming_template"], str)


@pytest.mark.req("FRG-API-013")
def test_put_naming_round_trips_and_takes_effect(client, tmp_path):
    series_id = client.portal.call(_seed_series_with_file, client.app, tmp_path / "library")

    put = client.put(
        "/api/v1/config/naming",
        json={
            "rename_enabled": True,
            "file_naming_template": _ROUNDTRIP_TEMPLATE,
            "folder_naming_template": "{Series Title} ({Year})",
            "replace_illegal_characters": True,
        },
    )
    assert put.status_code == 200

    # A subsequent GET reflects the new template...
    assert client.get("/api/v1/config/naming").json()["file_naming_template"] == _ROUNDTRIP_TEMPLATE
    # ...and the rename preview renders names using it (0000 padding → "0404").
    preview = client.get(f"/api/v1/rename?seriesId={series_id}").json()
    assert len(preview) == 1
    assert Path(preview[0]["newPath"]).name.startswith("Batman 0404 (1987)")


@pytest.mark.req("FRG-API-013")
def test_put_naming_blank_template_is_a_field_precise_400(client):
    resp = client.put(
        "/api/v1/config/naming",
        json={
            "rename_enabled": True,
            "file_naming_template": "   ",
            "folder_naming_template": "{Series Title} ({Year})",
            "replace_illegal_characters": True,
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert set(body) == {"message", "errors"}
    assert body["errors"][0]["field"] == "settings.file_naming_template"
    # Nothing changed: the stored template is still the default.
    assert "{Issue Number:000}" in client.get("/api/v1/config/naming").json()["file_naming_template"]


@pytest.mark.req("FRG-API-013")
def test_put_media_management_round_trips_its_fields(client, tmp_path):
    bin_dir = tmp_path / "recycle"
    bin_dir.mkdir()
    put = client.put(
        "/api/v1/config/mediamanagement",
        json={
            "import_transfer_mode": "copy",
            "library_import_mode": "move",
            "recycle_bin_path": str(bin_dir),
            "recycle_bin_retention_days": 14,
        },
    )
    assert put.status_code == 200
    got = client.get("/api/v1/config/mediamanagement").json()
    assert got == {
        "import_transfer_mode": "copy",
        "library_import_mode": "move",
        "recycle_bin_path": str(bin_dir),
        "recycle_bin_retention_days": 14,
    }
    # The running settings reflect the change.
    assert client.app.state.settings.import_transfer_mode == "copy"
    assert client.app.state.settings.recycle_bin_path == str(bin_dir)


@pytest.mark.req("FRG-API-013")
def test_put_media_management_bad_recycle_path_is_field_precise_400(client):
    resp = client.put(
        "/api/v1/config/mediamanagement",
        json={
            "import_transfer_mode": "move",
            "library_import_mode": "in_place",
            "recycle_bin_path": "/nonexistent-xyz/deeper/bin",
            "recycle_bin_retention_days": 0,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "settings.recycle_bin_path"
    # Unchanged: still the empty default.
    assert client.app.state.settings.recycle_bin_path == ""


@pytest.mark.req("FRG-PP-012")
def test_rename_execute_endpoint_enqueues_the_rename_command(client, tmp_path):
    series_id = client.portal.call(_seed_series_with_file, client.app, tmp_path / "library")
    resp = client.post("/api/v1/rename", json={"seriesId": series_id})
    assert resp.status_code == 201
    assert resp.json()["name"] == "rename-series"


@pytest.mark.req("FRG-API-013")
def test_no_secret_field_transits_the_config_resources(client, settings):
    secret_names = set(settings.secret_fields())
    assert secret_names  # there are secrets in the model
    for model in (NamingConfig, MediaManagementConfig):
        assert not (set(model.model_fields) & secret_names)
    # And no secret name appears in either GET response body.
    for path in ("/api/v1/config/naming", "/api/v1/config/mediamanagement"):
        assert not (set(client.get(path).json()) & secret_names)
