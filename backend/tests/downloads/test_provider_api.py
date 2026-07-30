"""FRG-DL-002 — download-client provider table shape + schema/test endpoints."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.db import DB_FILENAME, prepare_database
from downloads_support import SAB_BASE, SabFixture, make_sab_factory
from http_support import make_settings


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return make_settings(cfg)


def _client(settings, fixture: SabFixture) -> TestClient:
    app = create_app(settings)
    factory, _ = make_sab_factory(settings.config_dir, fixture)
    app.state.http_factory = factory  # test-injection seam (mirrors indexers)
    return TestClient(app)


def _test_body(**overrides):
    body_settings = {"base_url": SAB_BASE, "api_key": "sab-fake-key"}
    body_settings.update(overrides)
    return {"implementation": "sabnzbd", "settings": body_settings}


#: The key a saved client holds at rest — distinct from every key a test body
#: submits, so "the probe used the STORED one" cannot pass by coincidence.
STORED_KEY = "sab-stored-key-0000"
RETYPED_KEY = "sab-retyped-key-0000"


def _create_sab(client, api_key: str = STORED_KEY) -> int:
    """Persist one SABnzbd client and return its id."""
    resp = client.post(
        "/api/v1/downloadclient",
        json={
            "name": "SAB",
            "implementation": "sabnzbd",
            "settings": {"base_url": SAB_BASE, "api_key": api_key},
        },
    )
    assert resp.status_code == 201
    # The edit form is seeded from this shape: the secret is never in it, which
    # is precisely why a test of a saved client cannot resend the key.
    assert "api_key" not in resp.json()["settings"]
    return resp.json()["id"]


def _probe_keys(fixture: SabFixture) -> set[str | None]:
    """Every ``apikey`` the fixture SAB actually received."""
    return {r.url.params.get("apikey") for r in fixture.requests}


@pytest.mark.req("FRG-DL-001")
@pytest.mark.req("FRG-DL-002")
def test_migration_creates_all_six_change5_tables(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    with sqlite3.connect(cfg / DB_FILENAME) as conn:
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {
        "download_clients",
        "grab_history",
        "tracked_downloads",
        "blocklist",
        "remote_path_mappings",
        "ddl_queue",
    } <= tables


@pytest.mark.req("FRG-DL-002")
def test_schema_endpoint_mirrors_the_indexer_contract(settings):
    with _client(settings, SabFixture()) as client:
        resp = client.get("/api/v1/downloadclient/schema")
    assert resp.status_code == 200
    body = resp.json()
    sab = next(impl for impl in body if impl["implementation"] == "sabnzbd")
    assert sab["protocol"] == "usenet"
    names = [f["name"] for f in sab["fields"]]
    assert names == ["base_url", "api_key", "category", "priority"]
    for field in sab["fields"]:
        assert set(field) == {
            "order", "name", "type", "label", "help", "required",
            "secret", "advanced", "selectOptions",
        }
    # ddl is a first-class provider row from day one (FRG-DDL-001).
    assert any(impl["protocol"] == "ddl" for impl in body)


@pytest.mark.req("FRG-DL-002")
def test_secret_api_key_is_write_only_in_schema(settings):
    with _client(settings, SabFixture()) as client:
        resp = client.get("/api/v1/downloadclient/schema")
    api_key = next(
        f for impl in resp.json() for f in impl["fields"] if f["name"] == "api_key"
    )
    assert api_key["secret"] is True
    assert "value" not in api_key


@pytest.mark.req("FRG-DL-002")
def test_test_endpoint_runs_version_and_config_probe(settings):
    with _client(settings, SabFixture()) as client:
        resp = client.post("/api/v1/downloadclient/test", json=_test_body())
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["version"] == "4.3.2"


@pytest.mark.req("FRG-DL-002")
def test_test_endpoint_unreachable_sab_is_field_precise_failure(settings):
    fixture = SabFixture()
    fixture.sab_status = 503
    with _client(settings, fixture) as client:
        resp = client.post("/api/v1/downloadclient/test", json=_test_body())
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "base_url"


@pytest.mark.req("FRG-DL-002")
def test_test_endpoint_rejects_invalid_settings_with_field_errors(settings):
    with _client(settings, SabFixture()) as client:
        resp = client.post(
            "/api/v1/downloadclient/test",
            json={"implementation": "sabnzbd", "settings": {"api_key": "k"}},
        )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "settings.base_url"


@pytest.mark.req("FRG-DL-002")
def test_test_endpoint_rejects_unknown_implementation(settings):
    with _client(settings, SabFixture()) as client:
        resp = client.post(
            "/api/v1/downloadclient/test",
            json={"implementation": "nzbget", "settings": {}},
        )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "implementation"


@pytest.mark.req("FRG-DL-002")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_falls_back_to_the_stored_secret_for_a_saved_client(settings):
    # The write-only contract means the edit form has no api_key to send, so a
    # saved client could otherwise never be tested without retyping the key.
    fixture = SabFixture()
    with _client(settings, fixture) as client:
        client_id = _create_sab(client)
        fixture.requests.clear()
        resp = client.post(
            "/api/v1/downloadclient/test",
            json={
                "implementation": "sabnzbd",
                "settings": {"base_url": SAB_BASE},
                "client_id": client_id,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    # Decrypted, not the `enc:v1:` ciphertext SAB would reject.
    assert _probe_keys(fixture) == {STORED_KEY}


@pytest.mark.req("FRG-DL-002")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_treats_a_blank_submitted_secret_as_keep_stored(settings):
    fixture = SabFixture()
    with _client(settings, fixture) as client:
        client_id = _create_sab(client)
        fixture.requests.clear()
        resp = client.post(
            "/api/v1/downloadclient/test",
            json={
                "implementation": "sabnzbd",
                "settings": {"base_url": SAB_BASE, "api_key": ""},
                "client_id": client_id,
            },
        )
    assert resp.status_code == 200
    assert _probe_keys(fixture) == {STORED_KEY}


@pytest.mark.req("FRG-DL-002")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_prefers_a_retyped_secret_and_persists_nothing(settings):
    fixture = SabFixture()
    with _client(settings, fixture) as client:
        client_id = _create_sab(client)
        fixture.requests.clear()
        retyped = client.post(
            "/api/v1/downloadclient/test",
            json={
                "implementation": "sabnzbd",
                "settings": {"base_url": SAB_BASE, "api_key": RETYPED_KEY},
                "client_id": client_id,
            },
        )
        assert retyped.status_code == 200
        assert _probe_keys(fixture) == {RETYPED_KEY}

        # A test never writes: the row still holds the ORIGINAL key.
        fixture.requests.clear()
        again = client.post(
            "/api/v1/downloadclient/test",
            json={
                "implementation": "sabnzbd",
                "settings": {"base_url": SAB_BASE},
                "client_id": client_id,
            },
        )
    assert again.status_code == 200
    assert _probe_keys(fixture) == {STORED_KEY}


async def _backoff_health(app):
    from foragerr.providers.backoff import ProviderBackoff

    return await ProviderBackoff(app.state.db).health()


@pytest.mark.req("FRG-DL-002")
def test_test_endpoint_failure_leaves_the_backoff_ladder_untouched(settings):
    """A failed probe must not feed the shared back-off ladder: every pre-save
    test shares the transient id 0 (TransientBackoff, FRG-NFR-005), so a
    recorded failure here would throttle an unrelated future probe."""
    fixture = SabFixture()
    fixture.sab_status = 503
    with _client(settings, fixture) as client:
        resp = client.post("/api/v1/downloadclient/test", json=_test_body())
        assert resp.status_code == 400
        assert client.portal.call(_backoff_health, client.app) == []


@pytest.mark.req("FRG-DL-002")
@pytest.mark.req("FRG-API-009")
def test_merge_over_stored_keeps_blank_secret_but_overrides_blank_non_secret():
    """``_merge_over_stored``'s own contract: blank means "keep stored" ONLY
    for a secret field (write-only, so a form cannot resend it); every other
    submitted value — including a blank one — replaces the stored value. Unit
    level, not round-tripped through the live endpoint: SABnzbd's own
    ``category`` field further rejects an empty string (a downstream field
    constraint unrelated to the merge contract under test here)."""
    from foragerr.api.downloadclient import _merge_over_stored
    from foragerr.indexers.repo import serialize_settings

    from downloads_support import sab_settings

    stored_json = serialize_settings(
        sab_settings(api_key=STORED_KEY, category="custom-cat")
    )
    merged = _merge_over_stored(
        "sabnzbd",
        stored_json,
        {"base_url": SAB_BASE, "api_key": "", "category": ""},
    )
    # The secret fell back to the stored (still-encrypted) value...
    assert merged["api_key"] == json.loads(stored_json)["api_key"]
    assert merged["api_key"] != ""
    # ...but the non-secret blank value won over the stored "custom-cat".
    assert merged["category"] == ""


@pytest.mark.req("FRG-DL-002")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_maps_an_undecryptable_stored_secret_to_400(settings):
    """A saved client whose stored secret the CURRENT key cannot decrypt (key
    rotated/changed) must fail the field-precise way (400), not 500 — the
    same fail-soft contract already proven for PUT (FRG-AUTH-012)."""
    from cryptography.fernet import Fernet, MultiFernet

    from foragerr import keystore as keystore_mod

    fixture = SabFixture()
    with _client(settings, fixture) as client:
        client_id = _create_sab(client)

        wrong = keystore_mod.derive_fernet_key(
            "a-different-passphrase", b"0123456789abcdef"
        )
        keystore_mod.install_keystore(
            keystore_mod.Keystore(MultiFernet([Fernet(wrong)]), available=False)
        )

        resp = client.post(
            "/api/v1/downloadclient/test",
            json={
                "implementation": "sabnzbd",
                "settings": {"base_url": SAB_BASE},
                "client_id": client_id,
            },
        )
    assert resp.status_code == 400
    assert "decrypt" in resp.json()["message"]


@pytest.mark.req("FRG-DL-002")
def test_test_endpoint_rejects_an_unknown_client_id(settings):
    with _client(settings, SabFixture()) as client:
        resp = client.post(
            "/api/v1/downloadclient/test",
            json={
                "implementation": "sabnzbd",
                "settings": {"base_url": SAB_BASE},
                "client_id": 9999,
            },
        )
    assert resp.status_code == 404


@pytest.mark.req("FRG-DL-002")
def test_test_endpoint_rejects_an_implementation_that_is_not_the_rows(settings):
    # Merging one implementation's settings onto another's row would validate
    # against the wrong contract; the mismatch is a client bug, not a config one.
    with _client(settings, SabFixture()) as client:
        client_id = _create_sab(client)
        resp = client.post(
            "/api/v1/downloadclient/test",
            json={
                "implementation": "ddl",
                "settings": {},
                "client_id": client_id,
            },
        )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "implementation"


@pytest.mark.req("FRG-DL-002")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_without_a_client_id_still_requires_the_secret(settings):
    # The add form has no stored row to fall back on, so a missing secret there
    # is a correct field-precise refusal, not the bug the client_id path fixes.
    with _client(settings, SabFixture()) as client:
        resp = client.post(
            "/api/v1/downloadclient/test",
            json={"implementation": "sabnzbd", "settings": {"base_url": SAB_BASE}},
        )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "settings.api_key"
