"""Typed config resource endpoints: GET/PUT naming + media management (FRG-API-013).

Placed at the top level next to the other API tests (``test_library_config_api.py``);
the api-spec's suggested ``tests/api/`` path is the same coverage under a different
folder.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
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
@pytest.mark.req("FRG-PP-014")
def test_put_media_management_round_trips_its_fields(client, tmp_path):
    bin_dir = tmp_path / "recycle"
    bin_dir.mkdir()
    dump_dir = tmp_path / "dupes"
    dump_dir.mkdir()
    put = client.put(
        "/api/v1/config/mediamanagement",
        json={
            "import_transfer_mode": "copy",
            "library_import_mode": "move",
            "library_import_proposal_cap": 25,
            "library_import_similarity_floor": 0.7,
            "recycle_bin_path": str(bin_dir),
            "recycle_bin_retention_days": 14,
            "duplicate_constraint": "preferred-format",
            "duplicate_dump_path": str(dump_dir),
        },
    )
    assert put.status_code == 200
    got = client.get("/api/v1/config/mediamanagement").json()
    assert got == {
        "import_transfer_mode": "copy",
        "library_import_mode": "move",
        "library_import_proposal_cap": 25,
        "library_import_similarity_floor": 0.7,
        "recycle_bin_path": str(bin_dir),
        "recycle_bin_retention_days": 14,
        "duplicate_constraint": "preferred-format",
        "duplicate_dump_path": str(dump_dir),
    }
    # The running settings reflect the change.
    assert client.app.state.settings.import_transfer_mode == "copy"
    assert client.app.state.settings.recycle_bin_path == str(bin_dir)
    assert client.app.state.settings.duplicate_constraint == "preferred-format"
    assert client.app.state.settings.duplicate_dump_path == str(dump_dir)
    assert client.app.state.settings.library_import_proposal_cap == 25
    assert client.app.state.settings.library_import_similarity_floor == 0.7


def _mm_body(**overrides) -> dict:
    body = {
        "import_transfer_mode": "move",
        "library_import_mode": "in_place",
        "library_import_proposal_cap": 50,
        "library_import_similarity_floor": 0.5,
        "recycle_bin_path": "",
        "recycle_bin_retention_days": 0,
        "duplicate_constraint": "larger-size",
        "duplicate_dump_path": "",
    }
    body.update(overrides)
    return body


@pytest.mark.req("FRG-API-013")
def test_put_media_management_bad_recycle_path_is_field_precise_400(client):
    resp = client.put(
        "/api/v1/config/mediamanagement",
        json=_mm_body(recycle_bin_path="/nonexistent-xyz/deeper/bin"),
    )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "settings.recycle_bin_path"
    # Unchanged: still the empty default.
    assert client.app.state.settings.recycle_bin_path == ""


@pytest.mark.req("FRG-PP-014")
def test_media_management_defaults_include_the_duplicate_fields(client):
    got = client.get("/api/v1/config/mediamanagement").json()
    assert got["duplicate_constraint"] == "larger-size"  # documented default
    assert got["duplicate_dump_path"] == ""  # unset → normal disposal


@pytest.mark.req("FRG-IMP-023")
def test_media_management_defaults_include_the_library_import_knobs(client):
    got = client.get("/api/v1/config/mediamanagement").json()
    assert got["library_import_proposal_cap"] == 50  # documented default
    assert got["library_import_similarity_floor"] == 0.5


@pytest.mark.req("FRG-IMP-023")
def test_put_media_management_rejects_out_of_range_library_import_knobs(client):
    """The scan-tuning knobs validate field-precise like every other media-
    management setting: the cap must be >= 1, the floor within 0..1; nothing
    changes on rejection."""
    resp = client.put(
        "/api/v1/config/mediamanagement",
        json=_mm_body(library_import_proposal_cap=0),
    )
    assert resp.status_code == 400
    assert (
        resp.json()["errors"][0]["field"] == "settings.library_import_proposal_cap"
    )
    assert client.app.state.settings.library_import_proposal_cap == 50

    resp = client.put(
        "/api/v1/config/mediamanagement",
        json=_mm_body(library_import_similarity_floor=1.5),
    )
    assert resp.status_code == 400
    assert (
        resp.json()["errors"][0]["field"]
        == "settings.library_import_similarity_floor"
    )
    assert client.app.state.settings.library_import_similarity_floor == 0.5


@pytest.mark.req("FRG-PP-014")
def test_put_media_management_rejects_an_unknown_duplicate_constraint(client):
    resp = client.put(
        "/api/v1/config/mediamanagement",
        json=_mm_body(duplicate_constraint="biggest-wins"),
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["errors"][0]["field"] == "settings.duplicate_constraint"
    assert "larger-size" in body["errors"][0]["message"]
    assert client.app.state.settings.duplicate_constraint == "larger-size"


@pytest.mark.req("FRG-PP-014")
def test_put_media_management_bad_dump_path_is_field_precise_400(client):
    """The dump folder gets the same fail-fast writable-directory posture as the
    recycle bin."""
    resp = client.put(
        "/api/v1/config/mediamanagement",
        json=_mm_body(duplicate_dump_path="/nonexistent-xyz/deeper/dupes"),
    )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "settings.duplicate_dump_path"
    assert client.app.state.settings.duplicate_dump_path == ""


@pytest.mark.req("FRG-PP-012")
def test_rename_execute_endpoint_enqueues_the_rename_command(client, tmp_path):
    series_id = client.portal.call(_seed_series_with_file, client.app, tmp_path / "library")
    resp = client.post("/api/v1/rename", json={"seriesId": series_id})
    assert resp.status_code == 201
    assert resp.json()["name"] == "rename-series"


@pytest.mark.req("FRG-API-013")
@pytest.mark.req("FRG-UI-012")
def test_get_naming_tokens_exposes_the_shared_vocabulary(client):
    """The token endpoint mirrors the one canonical alias table verbatim so the
    settings UI never hand-maintains a duplicate token list (design decision 11)."""
    from foragerr.naming import DEFAULT_FILE_TEMPLATE, _TOKEN_ALIASES

    resp = client.get("/api/v1/config/naming/tokens")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"aliases", "defaults"}
    # Byte-for-byte the same table the renderer resolves tokens with.
    assert body["aliases"] == _TOKEN_ALIASES
    # A representative alias → canonical field mapping is present.
    assert body["aliases"]["series title"] == "series_title"
    assert body["aliases"]["issue number"] == "issue"
    # The default templates are carried so the UI can seed without duplicating.
    assert body["defaults"]["file_naming_template"] == DEFAULT_FILE_TEMPLATE


@pytest.mark.req("FRG-DEP-003")
def test_put_preserves_the_documented_config_comments(client, tmp_path):
    """A PUT rewrites config.yaml through the documented renderer, so the Field
    description comments the first-run file promised survive every write (they are
    not stripped down to bare key/value YAML)."""
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
    text = (Path(client.app.state.settings.config_dir) / "config.yaml").read_text(
        encoding="utf-8"
    )
    assert "# foragerr configuration" in text  # documented header
    assert "Token template for imported" in text  # a Field-description comment
    assert "file_naming_template:" in text  # and the live value line


@pytest.mark.req("FRG-API-013")
@pytest.mark.req("FRG-DEP-004")
async def test_concurrent_config_puts_do_not_lose_updates(tmp_path):
    """Two overlapping PUTs to the two config resources both persist: the
    lock-guarded read-modify-write re-reads the file the other just wrote, so one
    update can never silently clobber the other (lost-update guard)."""
    import asyncio
    from types import SimpleNamespace

    from foragerr.api.config_resources import (
        MediaManagementConfig,
        NamingConfig,
        _apply,
    )

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    bin_dir = tmp_path / "recycle"
    bin_dir.mkdir()
    settings = make_settings(cfg)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings))
    )
    naming_update = {
        "rename_enabled": False,
        "file_naming_template": _ROUNDTRIP_TEMPLATE,
        "folder_naming_template": "{Series Title} ({Year})",
        "replace_illegal_characters": True,
    }
    mm_update = {
        "import_transfer_mode": "copy",
        "library_import_mode": "move",
        "recycle_bin_path": str(bin_dir),
        "recycle_bin_retention_days": 14,
    }

    await asyncio.gather(
        _apply(request, naming_update, NamingConfig),
        _apply(request, mm_update, MediaManagementConfig),
    )

    parsed = yaml.safe_load((cfg / "config.yaml").read_text(encoding="utf-8"))
    assert parsed["rename_enabled"] is False  # the naming PUT persisted...
    assert parsed["recycle_bin_retention_days"] == 14  # ...and the mm PUT too
    assert parsed["recycle_bin_path"] == str(bin_dir)
    # The final in-memory settings reflect both changes as well.
    assert request.app.state.settings.rename_enabled is False
    assert request.app.state.settings.recycle_bin_path == str(bin_dir)


@pytest.mark.req("FRG-API-013")
def test_no_secret_field_transits_the_config_resources(client, settings):
    secret_names = set(settings.secret_fields())
    assert secret_names  # there are secrets in the model
    for model in (NamingConfig, MediaManagementConfig):
        assert not (set(model.model_fields) & secret_names)
    # And no secret name appears in either GET response body.
    for path in ("/api/v1/config/naming", "/api/v1/config/mediamanagement"):
        assert not (set(client.get(path).json()) & secret_names)
