"""HTTP contract tests for ``GET /series/lookup/volume/{cv_volume_id}``
(FRG-API-026).

Mirrors the style of the ``/lookup``/``/lookup/suggest`` tests in
``test_series_api.py``: a tiny self-contained ``volume/4050-{id}/`` handler
(rather than reusing ``flows_support.FakeCV``, which only models a
found-or-absent volume via a bare transport-level 404 — this route needs to
tell that apart from ComicVine's own "Object Not Found" envelope), built over
a real :class:`~foragerr.metadata.ComicVineClient` so the mapping/auth/lane
code paths are exercised exactly as production does.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from flows_support import FakeCV, build_factory, flows_settings
from foragerr.app import create_app
from foragerr.http import HttpClientFactory
from foragerr.library import repo
from foragerr.metadata import COMICVINE_CREDENTIAL_MESSAGE

from http_support import PUBLIC_V4, RecordingTransport, StubResolver

CV_HOST = "comicvine.gamespot.com"


# --- fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cv_gate():
    """Isolate the process-global ComicVine rate gate around every test in
    this file (mirrors ``test_series_api.py``'s own fixture of the same
    name — this file lives flat under ``backend/tests/`` too, so it doesn't
    pick up either packaged autouse fixture automatically)."""
    from foragerr.metadata import ratelimit

    ratelimit.reset_gate()
    yield
    ratelimit.reset_gate()


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


async def _create_root_folder(app, path: Path) -> int:
    async with app.state.db.write_session() as session:
        row = await repo.create_root_folder(session, str(path))
        return row.id


def make_root_folder(client, tmp_path: Path, name: str = "library-root") -> int:
    root = tmp_path / name
    root.mkdir()
    return client.portal.call(_create_root_folder, client.app, root)


def patch_comicvine(monkeypatch, factory) -> None:
    """Route every ComicVine call site an add-flow setup test drives at the
    injected factory (mirrors ``test_series_api.py``'s helper of the same
    name)."""
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _settings: factory)
    monkeypatch.setattr(
        "foragerr.library.flows.add.comicvine_factory", lambda _settings: factory
    )
    monkeypatch.setattr(
        "foragerr.library.flows.refresh.comicvine_factory", lambda _settings: factory
    )


# --- volume-detail double ------------------------------------------------------


def _volume_envelope(volume: dict) -> httpx.Response:
    payload = {"status_code": 1, "results": volume}
    return httpx.Response(200, content=json.dumps(payload).encode())


def _object_not_found_envelope() -> httpx.Response:
    """ComicVine's real shape for an unrecognized single-object id: a 200
    HTTP response whose JSON envelope carries ``status_code`` 101 ("Object
    Not Found") and an empty ``results`` — NOT a bare transport-level 404
    (that's a genuine outage/oddity, exercised separately below)."""
    payload = {"error": "Object Not Found", "status_code": 101, "results": []}
    return httpx.Response(200, content=json.dumps(payload).encode())


def _volume_handler(
    volumes: dict[int, dict] | None = None,
    *,
    not_found: bool = False,
    status: int = 200,
):
    """The one ``volume/4050-{id}/`` detail scaffold for every test below.

    ``not_found`` serves ComicVine's own "Object Not Found" envelope for any
    requested id; ``status`` != 200 rejects the request outright with that
    HTTP status (401 drives ``ComicVineAuthError``, 500 drives a generic
    transport-style ``ComicVineUnavailable``) — the two failure shapes this
    route must tell apart from a not-found id.
    """
    volumes = volumes or {}

    def _handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/volume/4050-" not in path:
            return httpx.Response(404, content=b"unknown endpoint")
        if status != 200:
            return httpx.Response(status, content=b"rejected")
        if not_found:
            return _object_not_found_envelope()
        vid = int(path.split("4050-")[1].rstrip("/"))
        volume = volumes.get(vid)
        if volume is None:
            return _object_not_found_envelope()
        return _volume_envelope(volume)

    return _handle


def _volume_factory(settings, handler):
    """Like ``flows_support.build_factory``, but also returns the
    ``RecordingTransport`` so a test can assert exactly how many upstream
    fetches were issued."""
    resolver = StubResolver({CV_HOST: [PUBLIC_V4]})
    transport = RecordingTransport(handler)
    factory = HttpClientFactory(settings, resolver=resolver, transport=transport)
    return factory, transport


# --- tests ---------------------------------------------------------------------


@pytest.mark.req("FRG-API-026")
def test_lookup_volume_known_id_returns_one_candidate(client, monkeypatch):
    factory, transport = _volume_factory(
        client.app.state.settings,
        _volume_handler({101: {"id": 101, "name": "Saga", "start_year": "2012"}}),
    )
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _settings: factory)

    response = client.get("/api/v1/series/lookup/volume/101")
    assert response.status_code == 200
    body = response.json()
    assert body["cv_volume_id"] == 101
    assert body["name"] == "Saga"
    assert body["start_year"] == 2012
    assert body["have_it"] is False
    # No pagination/degrade envelope on a single-object resolution.
    assert "complete" not in body
    assert "truncated" not in body
    # Exactly one upstream fetch for a single-id resolution.
    assert len(transport.requests) == 1
    assert "/volume/4050-101" in str(transport.requests[0].url)


@pytest.mark.req("FRG-API-026")
def test_lookup_volume_marks_have_it_true_for_an_existing_series(
    client, tmp_path, monkeypatch
):
    root_id = make_root_folder(client, tmp_path)
    add_factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(101, name="Saga").handler(),
    )
    patch_comicvine(monkeypatch, add_factory)
    created = client.post(
        "/api/v1/series", json={"cv_volume_id": 101, "root_folder_id": root_id}
    )
    assert created.status_code == 201

    factory, _transport = _volume_factory(
        client.app.state.settings,
        _volume_handler({101: {"id": 101, "name": "Saga", "start_year": "2012"}}),
    )
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _settings: factory)

    response = client.get("/api/v1/series/lookup/volume/101")
    assert response.status_code == 200
    assert response.json()["have_it"] is True


@pytest.mark.req("FRG-API-026")
def test_lookup_volume_unknown_id_is_structured_404(client, monkeypatch):
    """An id ComicVine reports as nonexistent (envelope status_code 101,
    "Object Not Found") yields a 404 — distinct from the 503 a transport
    failure gets in the next test."""
    factory, _transport = _volume_factory(
        client.app.state.settings, _volume_handler(not_found=True)
    )
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _settings: factory)

    response = client.get("/api/v1/series/lookup/volume/999999")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"message", "errors"}


@pytest.mark.req("FRG-API-026")
def test_lookup_volume_transport_failure_is_503_not_404(client, monkeypatch):
    """A genuine upstream failure (here, an unexpected 5xx from the volume
    detail endpoint) stays on the standard upstream-error mapping — NOT the
    structured 404 the previous test asserts for a not-found id, so a caller
    can tell "this id doesn't exist" apart from "ComicVine is unwell"."""
    factory, _transport = _volume_factory(
        client.app.state.settings, _volume_handler(status=500)
    )
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _settings: factory)

    response = client.get("/api/v1/series/lookup/volume/101")
    assert response.status_code == 503
    assert set(response.json()) == {"message", "errors"}


_LOOKUP_AUTH_MESSAGE = f"comicvine lookup failed: {COMICVINE_CREDENTIAL_MESSAGE}"


@pytest.mark.req("FRG-API-026")
def test_lookup_volume_auth_failure_is_503_naming_the_key_without_leaking_it(
    client, monkeypatch, caplog
):
    """A missing/invalid ComicVine key maps to the identical 503 contract the
    term lookup uses (reused mapping, not a parallel copy): the
    ``comicvine_api_key`` field discriminator, a static log line, and no key
    value in the response body or the captured logs."""
    factory, _transport = _volume_factory(
        client.app.state.settings, _volume_handler(status=401)
    )
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _settings: factory)

    with caplog.at_level(logging.WARNING, logger="foragerr.api.series"):
        response = client.get("/api/v1/series/lookup/volume/101")
    assert response.status_code == 503
    body = response.json()
    assert body["message"] == _LOOKUP_AUTH_MESSAGE
    assert body["errors"][0]["field"] == "comicvine_api_key"
    assert any(
        "series lookup rejected by ComicVine: API key missing or invalid"
        == record.getMessage()
        for record in caplog.records
    )
    assert "CV-SECRET-KEY-abc123" not in response.text
    assert "CV-SECRET-KEY-abc123" not in caplog.text


@pytest.mark.req("FRG-API-026")
def test_lookup_volume_unauthenticated_is_401_before_any_fetch(client, monkeypatch):
    """The route rides the same router as every other ``/series`` endpoint,
    so it inherits the app's default-deny perimeter with no route-local auth
    code — a bare request is refused before ComicVine is ever reached."""
    factory, transport = _volume_factory(
        client.app.state.settings,
        _volume_handler({101: {"id": 101, "name": "Saga", "start_year": "2012"}}),
    )
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _settings: factory)

    client.headers.pop("X-Api-Key", None)
    response = client.get("/api/v1/series/lookup/volume/101")
    assert response.status_code == 401
    assert transport.requests == []


@pytest.mark.req("FRG-API-026")
def test_lookup_volume_zero_id_is_400_field_cv_volume_id_before_any_fetch(
    client, monkeypatch
):
    """``cv_volume_id`` 0 is invalid locally — refused with a 400 naming the
    field, and ComicVine is never contacted (no interactive attempt is spent
    formatting a request that can only fail)."""
    factory, transport = _volume_factory(
        client.app.state.settings,
        _volume_handler({101: {"id": 101, "name": "Saga", "start_year": "2012"}}),
    )
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _settings: factory)

    response = client.get("/api/v1/series/lookup/volume/0")
    assert response.status_code == 400
    body = response.json()
    assert body["errors"][0]["field"] == "cv_volume_id"
    assert transport.requests == []  # no upstream fetch


@pytest.mark.req("FRG-API-026")
async def test_lookup_volume_non_positive_id_refused_before_touching_comicvine():
    """The ``cv_volume_id <= 0`` guard fires before the handler reaches the
    request, the factory, or ComicVine — proven by passing ``request=None`` and
    still getting the 400 (a negative id, which the integer path converter would
    not even route, is covered here for completeness)."""
    from foragerr.api.errors import ApiError
    from foragerr.api.series import lookup_volume

    for bad_id in (0, -1, -999):
        with pytest.raises(ApiError) as excinfo:
            await lookup_volume(bad_id, request=None)  # never dereferenced
        assert excinfo.value.status_code == 400
        assert excinfo.value.field == "cv_volume_id"


@pytest.mark.req("FRG-API-026")
def test_object_not_found_101_does_not_trip_the_auth_failure_health_dimension(
    client, monkeypatch
):
    """An "Object Not Found" (status_code 101) envelope is a VALID response that
    proves the key works — it clears the auth-failure health dimension rather
    than tripping it, so a stale/bad id never masquerades as a credential
    problem in the health surface (FRG-META-019)."""
    from foragerr.metadata import ratelimit

    # Pretend a prior request tripped the auth-failure dimension.
    ratelimit.gate().note_auth_failed()
    assert ratelimit.gate().is_auth_failed() is True

    factory, _transport = _volume_factory(
        client.app.state.settings, _volume_handler(not_found=True)
    )
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _settings: factory)

    response = client.get("/api/v1/series/lookup/volume/999999")
    assert response.status_code == 404
    # The 101 response cleared the auth-failure flag — it is not an auth failure.
    assert ratelimit.gate().is_auth_failed() is False
