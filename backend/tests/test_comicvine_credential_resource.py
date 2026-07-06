"""ComicVine credential settings resource (FRG-API-018) + live-apply (FRG-META-002).

The Settings → General resource lets the UI read the ComicVine key's configured
STATUS + SOURCE, UPDATE the key (persisted through the documented-config writer
and applied live by swapping ``app.state.settings``), and TEST connectivity —
without the key value EVER leaving the server in a response or a log line. These
tests pin every delta scenario:

- source reporting for env / file / unset, never the value;
- a non-blank PUT persists into ``config.yaml`` as a real value, applies live to
  the next ComicVine request with no restart, and registers the key with the
  log-redaction filter;
- a blank PUT keeps the stored key;
- an env-supplied key is reported ``source="environment"`` and rejected on write;
- the connectivity test's success / auth-failure contract (mirroring the indexer
  test button) with no key material in body or log.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import CONFIG_FILENAME
from foragerr.http import HttpClientFactory
from foragerr.logging import MASK, redact
from http_support import PUBLIC_V4, RecordingTransport, StubResolver, make_settings

CV_HOST = "comicvine.gamespot.com"
_KEY = "CV-SECRET-KEY-abc123"


@pytest.fixture(autouse=True)
def _reset_cv_gate():
    """Isolate the process-global ComicVine rate gate around every test (this
    file lives flat under ``tests/`` so it inherits no package autouse gate
    reset)."""
    from foragerr.metadata import ratelimit

    ratelimit.reset_gate()
    yield
    ratelimit.reset_gate()


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    # Fast CV interval so the live-apply lookup does not stall on the rate gate.
    return make_settings(cfg, comicvine_min_interval_seconds=0.25)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


class _CVRecorder:
    """A ComicVine transport double that records the ``api_key`` every request
    carried and answers an empty (or, when ``auth_fail``, a 401) search page.

    ``build_factory`` returns a factory whose ``external()`` client routes at
    this handler over a stub resolver + recording transport (no DNS, no
    network), so a test can assert exactly which key reached ComicVine."""

    def __init__(
        self,
        *,
        auth_fail: bool = False,
        server_error: bool = False,
        raise_timeout: bool = False,
    ) -> None:
        self.auth_fail = auth_fail
        self.server_error = server_error
        self.raise_timeout = raise_timeout
        self.seen_keys: list[str] = []

    def handler(self):
        def _handle(request: httpx.Request) -> httpx.Response:
            query = parse_qs(urlsplit(str(request.url)).query)
            self.seen_keys.append(query.get("api_key", [""])[0])
            if self.raise_timeout:
                # A transport-level timeout: suggest_series wraps every non-auth
                # upstream failure into complete=False (ComicVineUnavailable),
                # rather than raising.
                raise httpx.ReadTimeout("simulated timeout", request=request)
            if self.auth_fail:
                return httpx.Response(401, content=b"invalid api key")
            if self.server_error:
                return httpx.Response(500, content=b"upstream boom")
            body = {"status_code": 1, "results": [], "number_of_total_results": 0}
            return httpx.Response(200, content=json.dumps(body).encode())

        return _handle

    def factory(self, settings) -> HttpClientFactory:
        resolver = StubResolver({CV_HOST: [PUBLIC_V4]})
        transport = RecordingTransport(self.handler())
        return HttpClientFactory(settings, resolver=resolver, transport=transport)


def _patch_cv(monkeypatch, recorder: _CVRecorder) -> None:
    """Route both the credential-resource test action and the series-lookup
    route at the recorder, so a UI-written key can be observed reaching CV."""
    monkeypatch.setattr(
        "foragerr.api.config_resources.comicvine_factory", recorder.factory
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", recorder.factory
    )


# --- GET: status + source, never the value (FRG-API-018) --------------------


@pytest.mark.req("FRG-API-018")
def test_get_reports_unset_when_no_key_configured(client):
    body = client.get("/api/v1/config/general").json()
    assert body == {"comicvine_api_key": {"configured": False, "source": "unset"}}


@pytest.mark.req("FRG-API-018")
def test_get_reports_file_source_and_never_the_value(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    settings = make_settings(cfg, comicvine_api_key=_KEY)
    app = create_app(settings)
    with TestClient(app) as client:
        resp = client.get("/api/v1/config/general")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "comicvine_api_key": {"configured": True, "source": "file"}
        }
        # The value (and no substring of it) is not in the response.
        assert _KEY not in resp.text


@pytest.mark.req("FRG-API-018")
@pytest.mark.req("FRG-META-002")
def test_get_reports_environment_source_when_env_set(client, monkeypatch):
    monkeypatch.setenv("FORAGERR_COMICVINE_API_KEY", _KEY)
    resp = client.get("/api/v1/config/general")
    body = resp.json()
    assert body == {
        "comicvine_api_key": {"configured": True, "source": "environment"}
    }
    assert _KEY not in resp.text


# --- PUT: persist + live-apply + redaction (FRG-API-018 / FRG-META-002) ------


@pytest.mark.req("FRG-API-018")
@pytest.mark.req("FRG-META-002")
def test_put_persists_key_applies_live_and_registers_redaction(
    client, monkeypatch
):
    recorder = _CVRecorder()
    _patch_cv(monkeypatch, recorder)

    put = client.put(
        "/api/v1/config/general", json={"comicvine_api_key": _KEY}
    )
    assert put.status_code == 200
    # The response reports the new status/source but NEVER echoes the key.
    assert put.json() == {
        "comicvine_api_key": {"configured": True, "source": "file"}
    }
    assert _KEY not in put.text

    # It is written into config.yaml as a REAL value via the documented writer.
    config_text = (
        Path(client.app.state.settings.config_dir) / CONFIG_FILENAME
    ).read_text(encoding="utf-8")
    assert "# foragerr configuration" in config_text  # documented header intact
    parsed = yaml.safe_load(config_text)
    assert parsed["comicvine_api_key"] == _KEY  # uncommented, real value

    # The running settings picked up the new key (swap = live-apply)...
    assert client.app.state.settings.comicvine_api_key.get_secret_value() == _KEY
    # ...and the very next ComicVine request uses it WITHOUT a restart.
    lookup = client.get("/api/v1/series/lookup", params={"term": "batman"})
    assert lookup.status_code == 200
    assert recorder.seen_keys and recorder.seen_keys[-1] == _KEY

    # The key was registered with the redaction filter (masked everywhere).
    assert redact(f"lookup used {_KEY}") == f"lookup used {MASK}"


@pytest.mark.req("FRG-API-018")
def test_blank_put_keeps_the_stored_key(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    settings = make_settings(cfg, comicvine_api_key=_KEY)
    app = create_app(settings)
    with TestClient(app) as client:
        put = client.put("/api/v1/config/general", json={"comicvine_api_key": ""})
        assert put.status_code == 200
        # The stored key is retained, not cleared.
        assert (
            client.app.state.settings.comicvine_api_key.get_secret_value() == _KEY
        )
        assert client.get("/api/v1/config/general").json() == {
            "comicvine_api_key": {"configured": True, "source": "file"}
        }


@pytest.mark.req("FRG-API-018")
@pytest.mark.req("FRG-META-002")
def test_env_supplied_key_is_reported_readonly_and_rejects_writes(
    client, monkeypatch
):
    monkeypatch.setenv("FORAGERR_COMICVINE_API_KEY", _KEY)
    put = client.put(
        "/api/v1/config/general", json={"comicvine_api_key": "new-value"}
    )
    assert put.status_code == 409
    body = put.json()
    # The rejection names the environment variable and is field-precise.
    assert "FORAGERR_COMICVINE_API_KEY" in body["message"]
    assert body["errors"][0]["field"] == "comicvine_api_key"
    # Nothing was persisted: no config.yaml key line was written.
    config_file = Path(client.app.state.settings.config_dir) / CONFIG_FILENAME
    if config_file.exists():
        parsed = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        assert parsed.get("comicvine_api_key") in (None, "")
    # The attempted new value never appears in the response.
    assert "new-value" not in put.text


# --- Connectivity test contract (FRG-API-018) -------------------------------


@pytest.mark.req("FRG-API-018")
def test_connectivity_test_success(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    settings = make_settings(
        cfg, comicvine_api_key=_KEY, comicvine_min_interval_seconds=0.25
    )
    app = create_app(settings)
    recorder = _CVRecorder()
    _patch_cv(monkeypatch, recorder)
    with TestClient(app) as client:
        resp = client.post("/api/v1/config/comicvine/test")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        # The EFFECTIVE key was exercised, but never returned in the body.
        assert recorder.seen_keys and recorder.seen_keys[-1] == _KEY
        assert _KEY not in resp.text


@pytest.mark.req("FRG-API-018")
def test_connectivity_test_auth_failure(tmp_path, monkeypatch, caplog):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    settings = make_settings(
        cfg, comicvine_api_key=_KEY, comicvine_min_interval_seconds=0.25
    )
    app = create_app(settings)
    recorder = _CVRecorder(auth_fail=True)
    _patch_cv(monkeypatch, recorder)
    with TestClient(app) as client:
        with caplog.at_level(logging.WARNING):
            resp = client.post("/api/v1/config/comicvine/test")
    assert resp.status_code == 400
    body = resp.json()
    # Field-precise credential failure, mirroring the indexer test contract.
    assert body["errors"][0]["field"] == "comicvine_api_key"
    # Neither the response body nor any log line carries the key value.
    assert _KEY not in resp.text
    assert _KEY not in "\n".join(r.getMessage() for r in caplog.records)


_TEST_STATIC_MESSAGE = (
    "comicvine test failed: service unreachable or returned an error"
)


@pytest.mark.req("FRG-API-018")
def test_connectivity_test_upstream_500_reports_failure(tmp_path, monkeypatch, caplog):
    """A 5xx from ComicVine must NOT degrade to a 200 success. suggest_series
    swallows every non-auth upstream error into complete=False, so the endpoint
    inspects the result and returns a field-null 400 with a STATIC message."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    settings = make_settings(
        cfg, comicvine_api_key=_KEY, comicvine_min_interval_seconds=0.25
    )
    app = create_app(settings)
    recorder = _CVRecorder(server_error=True)
    _patch_cv(monkeypatch, recorder)
    with TestClient(app) as client:
        with caplog.at_level(logging.WARNING):
            resp = client.post("/api/v1/config/comicvine/test")
    assert resp.status_code == 400
    body = resp.json()
    assert body["message"] == _TEST_STATIC_MESSAGE
    # field is null (whole-operation failure, not a field-precise one).
    assert body["errors"] == []
    # The static message carries no dynamic upstream text or key material.
    assert _KEY not in resp.text
    assert "500" not in resp.text
    assert _KEY not in "\n".join(r.getMessage() for r in caplog.records)


@pytest.mark.req("FRG-API-018")
def test_connectivity_test_upstream_timeout_reports_failure(tmp_path, monkeypatch):
    """A transport timeout (ComicVineUnavailable) takes the same honest path as
    a 5xx: complete=False ⇒ field-null 400 with the static message."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    settings = make_settings(
        cfg, comicvine_api_key=_KEY, comicvine_min_interval_seconds=0.25
    )
    app = create_app(settings)
    recorder = _CVRecorder(raise_timeout=True)
    _patch_cv(monkeypatch, recorder)
    with TestClient(app) as client:
        resp = client.post("/api/v1/config/comicvine/test")
    assert resp.status_code == 400
    body = resp.json()
    assert body["message"] == _TEST_STATIC_MESSAGE
    assert body["errors"] == []
    assert _KEY not in resp.text


# --- Env-source detection matches pydantic's effective behavior (FRG-API-018)


@pytest.mark.req("FRG-API-018")
@pytest.mark.req("FRG-META-002")
def test_lowercase_env_spelling_is_detected_as_environment(client, monkeypatch):
    """pydantic-settings matches env names case-insensitively, so a lowercase
    ``foragerr_comicvine_api_key`` shadows the file just as the uppercase
    spelling does. The source helper must scan case-insensitively or it would
    report ``file``/``unset`` while the env value actually wins — a silently
    ineffective editor. GET reports ``environment``; PUT is rejected 409."""
    monkeypatch.setenv("foragerr_comicvine_api_key", _KEY)
    get = client.get("/api/v1/config/general")
    assert get.json() == {
        "comicvine_api_key": {"configured": True, "source": "environment"}
    }
    assert _KEY not in get.text
    put = client.put(
        "/api/v1/config/general", json={"comicvine_api_key": "new-value"}
    )
    assert put.status_code == 409
    assert "FORAGERR_COMICVINE_API_KEY" in put.json()["message"]


@pytest.mark.req("FRG-API-018")
@pytest.mark.req("FRG-META-002")
def test_empty_env_does_not_shadow_file_key(tmp_path, monkeypatch):
    """An EMPTY ``FORAGERR_COMICVINE_API_KEY=""`` must not shadow the file key:
    ``env_ignore_empty=True`` makes pydantic ignore it (the effective key is the
    file's), and the source helper skips empty env values to match — reporting
    ``file`` and allowing an effective PUT."""
    monkeypatch.setenv("FORAGERR_COMICVINE_API_KEY", "")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    settings = make_settings(
        cfg, comicvine_api_key=_KEY, comicvine_min_interval_seconds=0.25
    )
    app = create_app(settings)
    # The empty env value did not shadow the file: the effective key is the file's.
    assert app.state.settings.comicvine_api_key.get_secret_value() == _KEY
    recorder = _CVRecorder()
    _patch_cv(monkeypatch, recorder)
    with TestClient(app) as client:
        assert client.get("/api/v1/config/general").json() == {
            "comicvine_api_key": {"configured": True, "source": "file"}
        }
        # PUT is allowed (not env-managed) and applies live.
        new_key = "CV-NEW-KEY-xyz789"
        put = client.put(
            "/api/v1/config/general", json={"comicvine_api_key": new_key}
        )
        assert put.status_code == 200
        assert (
            client.app.state.settings.comicvine_api_key.get_secret_value()
            == new_key
        )


@pytest.mark.req("FRG-API-018")
def test_no_key_material_in_any_response_or_log(tmp_path, monkeypatch, caplog):
    """Aggregate guard across read + update + test: no response body and no
    emitted log line contains the ComicVine key value."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    settings = make_settings(cfg, comicvine_min_interval_seconds=0.25)
    app = create_app(settings)
    recorder = _CVRecorder()
    _patch_cv(monkeypatch, recorder)
    with TestClient(app) as client:
        with caplog.at_level(logging.DEBUG):
            get = client.get("/api/v1/config/general")
            put = client.put(
                "/api/v1/config/general", json={"comicvine_api_key": _KEY}
            )
            test = client.post("/api/v1/config/comicvine/test")
    for resp in (get, put, test):
        assert _KEY not in resp.text
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert _KEY not in logged
