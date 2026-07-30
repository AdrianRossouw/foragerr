"""Indexer schema + test HTTP endpoints (FRG-IDX-003, FRG-API-009)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from indexers_support import IDX_BASE, caps_doc, make_factory
from http_support import make_settings


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return make_settings(cfg)


def _client(settings, handler) -> TestClient:
    app = create_app(settings)
    factory, _ = make_factory(settings.config_dir, handler)
    app.state.http_factory = factory  # test-injection seam
    return TestClient(app)


def _test_body(**settings_overrides):
    body_settings = {"base_url": IDX_BASE, "api_key": "idx-fake-key-0000"}
    body_settings.update(settings_overrides)
    return {"implementation": "newznab", "settings": body_settings}


#: The key a saved indexer holds at rest — distinct from every key a test body
#: submits, so "the probe used the STORED one" cannot pass by coincidence.
STORED_KEY = "idx-stored-key-0000"
RETYPED_KEY = "idx-retyped-key-0000"


def _caps_recorder(seen: list[str | None]):
    """A caps handler recording the ``apikey`` each probe actually presented."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("apikey"))
        return httpx.Response(200, content=caps_doc())

    return handler


def _create_newznab(client, api_key: str = STORED_KEY) -> int:
    """Persist one DISABLED newznab indexer and return its id.

    Disabled so creating it is not the zero-to-one enabled transition that
    enqueues a backlog sweep (FRG-SCHED-012) — the sweep would issue indexer
    traffic of its own and blur what the probe presented. ``/test`` is
    indifferent to the flag."""
    resp = client.post(
        "/api/v1/indexer",
        json={
            "implementation": "newznab",
            "name": "Example Indexer",
            "settings": {"base_url": IDX_BASE, "api_key": api_key},
            "enabled": False,
        },
    )
    assert resp.status_code == 201
    # The edit form is seeded from this shape: the secret is never in it, which
    # is precisely why a test of a saved indexer cannot resend the key.
    assert "api_key" not in resp.json()["settings"]
    return resp.json()["id"]


@pytest.mark.req("FRG-API-009")
@pytest.mark.req("FRG-IDX-003")
def test_schema_endpoint_returns_renderable_field_metadata(settings):
    with _client(settings, lambda r: httpx.Response(200)) as client:
        resp = client.get("/api/v1/indexer/schema")
    assert resp.status_code == 200
    body = resp.json()
    newznab = next(impl for impl in body if impl["implementation"] == "newznab")
    names = [f["name"] for f in newznab["fields"]]
    assert names == ["base_url", "api_key", "categories", "additional_parameters"]
    for f in newznab["fields"]:
        assert set(f) == {
            "order", "name", "type", "label", "help", "required",
            "secret", "advanced", "selectOptions",
        }
    orders = [f["order"] for f in newznab["fields"]]
    assert orders == sorted(orders)  # stable declared order


@pytest.mark.req("FRG-API-009")
def test_secret_fields_are_write_only_and_never_echoed(settings):
    with _client(settings, lambda r: httpx.Response(200)) as client:
        resp = client.get("/api/v1/indexer/schema")
    api_key = next(
        f
        for impl in resp.json()
        for f in impl["fields"]
        if f["name"] == "api_key"
    )
    assert api_key["secret"] is True
    assert "value" not in api_key  # no value surfaced anywhere
    assert "idx-fake-key" not in resp.text  # no secret material in the schema


@pytest.mark.req("FRG-IDX-003")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_runs_live_caps_probe_and_reports_success(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("t") == "caps"
        return httpx.Response(200, content=caps_doc())

    with _client(settings, handler) as client:
        resp = client.post("/api/v1/indexer/test", json=_test_body())
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["categories"]["7030"] == "Comics"
    assert body["degraded"] is False


@pytest.mark.req("FRG-IDX-003")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_maps_wrong_key_to_field_precise_auth_failure(settings):
    with _client(settings, lambda r: httpx.Response(401)) as client:
        resp = client.post("/api/v1/indexer/test", json=_test_body())
    assert resp.status_code == 400
    body = resp.json()
    assert body["errors"][0]["field"] == "api_key"  # field-precise, not generic


@pytest.mark.req("FRG-IDX-001")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_rejects_invalid_settings_with_field_errors(settings):
    # Missing base_url — validation fails before any probe; nothing persisted.
    with _client(settings, lambda r: httpx.Response(200)) as client:
        resp = client.post(
            "/api/v1/indexer/test",
            json={"implementation": "newznab", "settings": {"api_key": "k"}},
        )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "settings.base_url"


@pytest.mark.req("FRG-API-009")
def test_test_endpoint_rejects_unknown_implementation(settings):
    with _client(settings, lambda r: httpx.Response(200)) as client:
        resp = client.post(
            "/api/v1/indexer/test",
            json={"implementation": "torznab", "settings": {}},
        )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "implementation"


@pytest.mark.req("FRG-IDX-003")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_falls_back_to_the_stored_secret_for_a_saved_indexer(settings):
    # The write-only contract means the edit form has no api_key to send, so a
    # saved indexer could otherwise never be tested without retyping the key.
    seen: list[str | None] = []
    with _client(settings, _caps_recorder(seen)) as client:
        indexer_id = _create_newznab(client)
        resp = client.post(
            "/api/v1/indexer/test",
            json={
                "implementation": "newznab",
                "settings": {"base_url": IDX_BASE},
                "indexer_id": indexer_id,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    # Decrypted, not the `enc:v1:` ciphertext an indexer would reject.
    assert seen == [STORED_KEY]


@pytest.mark.req("FRG-IDX-003")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_treats_a_blank_submitted_secret_as_keep_stored(settings):
    seen: list[str | None] = []
    with _client(settings, _caps_recorder(seen)) as client:
        indexer_id = _create_newznab(client)
        resp = client.post(
            "/api/v1/indexer/test",
            json={
                "implementation": "newznab",
                "settings": {"base_url": IDX_BASE, "api_key": ""},
                "indexer_id": indexer_id,
            },
        )
    assert resp.status_code == 200
    assert seen == [STORED_KEY]


@pytest.mark.req("FRG-IDX-003")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_prefers_a_retyped_secret_and_persists_nothing(settings):
    seen: list[str | None] = []
    with _client(settings, _caps_recorder(seen)) as client:
        indexer_id = _create_newznab(client)
        retyped = client.post(
            "/api/v1/indexer/test",
            json={
                "implementation": "newznab",
                "settings": {"base_url": IDX_BASE, "api_key": RETYPED_KEY},
                "indexer_id": indexer_id,
            },
        )
        assert retyped.status_code == 200

        # A test never writes: the row still holds the ORIGINAL key.
        again = client.post(
            "/api/v1/indexer/test",
            json={
                "implementation": "newznab",
                "settings": {"base_url": IDX_BASE},
                "indexer_id": indexer_id,
            },
        )
    assert again.status_code == 200
    assert seen == [RETYPED_KEY, STORED_KEY]


@pytest.mark.req("FRG-IDX-003")
def test_test_endpoint_rejects_an_unknown_indexer_id(settings):
    with _client(settings, lambda r: httpx.Response(200)) as client:
        resp = client.post(
            "/api/v1/indexer/test",
            json={
                "implementation": "newznab",
                "settings": {"base_url": IDX_BASE},
                "indexer_id": 9999,
            },
        )
    assert resp.status_code == 404


@pytest.mark.req("FRG-IDX-003")
def test_test_endpoint_rejects_an_implementation_that_is_not_the_rows(settings):
    # Merging one implementation's settings onto another's row would validate
    # against the wrong contract; the mismatch is a client bug, not a config one.
    with _client(settings, lambda r: httpx.Response(200)) as client:
        indexer_id = _create_newznab(client)
        resp = client.post(
            "/api/v1/indexer/test",
            json={
                "implementation": "getcomics",
                "settings": {},
                "indexer_id": indexer_id,
            },
        )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "implementation"


@pytest.mark.req("FRG-IDX-003")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_without_an_indexer_id_still_requires_the_secret(settings):
    # The add form has no stored row to fall back on, so a missing secret there
    # is a correct field-precise refusal, not the bug the indexer_id path fixes.
    with _client(settings, lambda r: httpx.Response(200)) as client:
        resp = client.post(
            "/api/v1/indexer/test",
            json={"implementation": "newznab", "settings": {"base_url": IDX_BASE}},
        )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "settings.api_key"
