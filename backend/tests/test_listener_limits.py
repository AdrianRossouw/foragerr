"""Listener inbound request resource limits — HTTP arm + config keys
(FRG-NFR-014).

Covers the ``api/limits.py`` middleware (body/header/timeout/per-client-rate
caps + request-field log sanitization) and the new documented config keys
(the listener_* HTTP keys plus the ws_* keys consumed by the WebSocket area).
The WebSocket connection-cap / inbound-frame limits themselves live in
``foragerr.ws`` and are tested there; here we pin that the middleware never
touches the websocket scope.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from foragerr.api.limits import (
    RequestLimitsMiddleware,
    _RequestBodyTooLarge,
    _SlidingWindowRateLimiter,
    sanitize_log_field,
)
from foragerr.config import (
    CONFIG_FILENAME,
    INTERVAL_RANGES,
    Settings,
    load_settings,
    render_documented_config,
)

# --------------------------------------------------------------------------
# Test app factory
# --------------------------------------------------------------------------


def _make_app(**overrides) -> FastAPI:
    """A minimal app with the limits middleware and a few probe routes.

    Defaults keep every limit generous / rate limiting OFF so a test opts into
    exactly the one control it exercises.
    """
    limits = dict(
        max_body_bytes=1024,
        max_header_bytes=16 * 1024,
        request_timeout_seconds=30,
        rate_max_requests=0,
        rate_window_seconds=1,
    )
    limits.update(overrides)

    app = FastAPI()
    app.add_middleware(RequestLimitsMiddleware, **limits)

    @app.post("/echo")
    async def echo(request: Request):
        body = await request.body()
        return {"len": len(body)}

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    @app.get("/slow")
    async def slow():
        await asyncio.sleep(5)  # never responds within a short timeout
        return {"ok": True}

    @app.get("/stream")
    async def stream():
        async def gen():
            yield b"AAAA"  # first byte lands immediately -> response starts
            await asyncio.sleep(0.5)  # then a gap longer than a short timeout
            yield b"BBBB"

        return StreamingResponse(gen())

    return app


# --------------------------------------------------------------------------
# Config keys (task 1.1)
# --------------------------------------------------------------------------

_NEW_KEYS = {
    "listener_max_body_bytes": 8 * 1024 * 1024,
    "listener_max_header_bytes": 16 * 1024,
    "listener_request_timeout_seconds": 30,
    "listener_rate_max_requests": 240,
    "listener_rate_window_seconds": 1,
    "ws_max_connections": 32,
    "ws_max_inbound_bytes": 4096,
    "ws_max_inbound_messages_per_second": 10,
}


@pytest.mark.req("FRG-NFR-014")
def test_new_limit_keys_have_documented_defaults():
    """Every new listener/WS key carries its documented default on Settings."""
    settings = Settings(config_dir="/tmp")
    for name, default in _NEW_KEYS.items():
        assert name in Settings.model_fields, name
        assert getattr(settings, name) == default, name


@pytest.mark.req("FRG-NFR-014")
def test_new_limit_keys_rendered_into_documented_config():
    """render_documented_config emits each new key with its default value line,
    so first-run config.yaml documents them (FRG-DEP-003 treatment)."""
    text = render_documented_config()
    for name, default in _NEW_KEYS.items():
        assert f"{name}:" in text, name
        assert f"# default: {default}" in text, name


@pytest.mark.req("FRG-NFR-014")
def test_ws_keys_present_for_area_2_consumption():
    """The ws_* keys land on Settings here (single writer of config.py) so the
    WebSocket area can consume them with the documented defaults."""
    settings = Settings(config_dir="/tmp")
    assert settings.ws_max_connections == 32
    assert settings.ws_max_inbound_bytes == 4096
    assert settings.ws_max_inbound_messages_per_second == 10


@pytest.mark.req("FRG-NFR-014")
def test_interval_keys_registered_for_clamp():
    """Both interval-shaped listener keys join INTERVAL_RANGES for the
    clamp-with-warning path, and their descriptions name the enforced range."""
    for name in ("listener_request_timeout_seconds", "listener_rate_window_seconds"):
        assert name in INTERVAL_RANGES, name
        lo, hi = INTERVAL_RANGES[name]
        assert f"{lo}..{hi}" in (Settings.model_fields[name].description or "")


@pytest.mark.req("FRG-NFR-014")
@pytest.mark.req("FRG-NFR-009")
def test_out_of_range_listener_timeout_clamped_with_warning(config_dir, caplog):
    """An out-of-range request timeout clamps to the documented ceiling with a
    warning (the FRG-NFR-009 clamp path), not a hard failure."""
    (config_dir / CONFIG_FILENAME).write_text(
        "listener_request_timeout_seconds: 99999\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING, logger="foragerr.config"):
        settings = load_settings()
    assert settings.listener_request_timeout_seconds == 300  # documented ceiling
    warning = next(
        r for r in caplog.records
        if "listener_request_timeout_seconds" in r.getMessage()
    )
    assert warning.levelno == logging.WARNING


@pytest.mark.req("FRG-NFR-014")
@pytest.mark.req("FRG-NFR-009")
def test_out_of_range_rate_window_clamped_with_warning(config_dir, caplog):
    (config_dir / CONFIG_FILENAME).write_text(
        "listener_rate_window_seconds: 0\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING, logger="foragerr.config"):
        settings = load_settings()
    assert settings.listener_rate_window_seconds == 1  # documented floor
    assert any(
        "listener_rate_window_seconds" in r.getMessage() for r in caplog.records
    )


@pytest.mark.req("FRG-NFR-014")
def test_rate_max_requests_zero_is_accepted_not_clamped():
    """The rate cap's 0-disables value is a real setting, not an interval that
    gets clamped up to a floor."""
    assert "listener_rate_max_requests" not in INTERVAL_RANGES
    assert Settings(config_dir="/tmp", listener_rate_max_requests=0).listener_rate_max_requests == 0


# --------------------------------------------------------------------------
# Body size cap (task 1.2)
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-014")
def test_oversize_content_length_body_rejected_413():
    """A declared Content-Length over the cap is refused with 413 immediately."""
    with TestClient(_make_app(max_body_bytes=1024)) as client:
        resp = client.post("/echo", content=b"x" * 4096)
    assert resp.status_code == 413


@pytest.mark.req("FRG-NFR-014")
def test_chunked_drip_without_content_length_rejected_at_cap():
    """A chunked body with no Content-Length that drips past the cap is aborted
    with 413 by the streaming counter (not the fast Content-Length path)."""
    def drip():
        for _ in range(100_000):
            yield b"x" * 256

    with TestClient(_make_app(max_body_bytes=1024)) as client:
        resp = client.post("/echo", content=drip())
    assert resp.status_code == 413


@pytest.mark.req("FRG-NFR-014")
async def test_streaming_body_counter_aborts_without_unbounded_buffer():
    """The receive wrapper aborts at the cap after a BOUNDED number of reads —
    it never accumulates the whole body in memory (the load-bearing anti-DoS
    property for an omitted/lying Content-Length)."""
    reads = {"n": 0}

    async def infinite_receive():
        reads["n"] += 1
        return {"type": "http.request", "body": b"x" * 256, "more_body": True}

    mw = RequestLimitsMiddleware(
        None,
        max_body_bytes=1024,
        max_header_bytes=1,
        request_timeout_seconds=1,
        rate_max_requests=0,
        rate_window_seconds=1,
    )
    wrapped = mw._body_capped_receive(infinite_receive)
    with pytest.raises(_RequestBodyTooLarge):
        for _ in range(1_000_000):
            await wrapped()
    # 1024-byte cap over 256-byte chunks: aborts on the 5th read, never buffers
    # the (unbounded) remainder.
    assert reads["n"] == 5


@pytest.mark.req("FRG-NFR-014")
def test_normal_small_json_request_is_unaffected():
    """A normal small-JSON request passes every control untouched."""
    with TestClient(_make_app()) as client:
        resp = client.post("/echo", json={"a": 1})
        assert resp.status_code == 200
        assert resp.json()["len"] > 0
        assert client.get("/ok").status_code == 200


# --------------------------------------------------------------------------
# Header size cap (task 1.2)
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-014")
def test_oversize_headers_rejected_431():
    with TestClient(_make_app(max_header_bytes=2048)) as client:
        resp = client.get("/ok", headers={"X-Big": "a" * 4000})
        assert resp.status_code == 431
        assert client.get("/ok").status_code == 200  # normal headers fine


# --------------------------------------------------------------------------
# Request timeout (task 1.2)
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-014")
def test_hung_handler_times_out_with_503():
    """A handler that produces no response within the timeout is aborted with a
    bounded 503, releasing the worker rather than wedging."""
    with TestClient(_make_app(request_timeout_seconds=0.3)) as client:
        resp = client.get("/slow")
    assert resp.status_code == 503


@pytest.mark.req("FRG-NFR-014")
def test_streaming_response_not_truncated_by_timeout():
    """A response that has already started streaming (an OPDS download, an SPA
    asset) is exempt from the timeout — the bound is time-to-first-byte, so a
    slow-but-progressing stream completes in full and is never cut to 503."""
    with TestClient(_make_app(request_timeout_seconds=0.2)) as client:
        resp = client.get("/stream")  # first byte immediate, 0.5s mid-stream gap
    assert resp.status_code == 200
    assert resp.content == b"AAAABBBB"


# --------------------------------------------------------------------------
# Per-client rate cap (task 1.2)
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-014")
def test_burst_from_one_client_is_rate_limited_429_with_retry_after():
    with TestClient(_make_app(rate_max_requests=3, rate_window_seconds=60)) as client:
        codes = [client.get("/ok").status_code for _ in range(4)]
        over = client.get("/ok")
    assert codes == [200, 200, 200, 429]
    assert over.status_code == 429
    assert over.headers.get("retry-after") is not None
    assert int(over.headers["retry-after"]) >= 1


@pytest.mark.req("FRG-NFR-014")
def test_rate_cap_zero_disables_limiting():
    with TestClient(_make_app(rate_max_requests=0)) as client:
        assert all(client.get("/ok").status_code == 200 for _ in range(50))


@pytest.mark.req("FRG-NFR-014")
def test_rate_limiter_client_table_stays_bounded():
    """A flood of distinct (possibly spoofed) peer addresses can never grow the
    limiter's own client table past its LRU cap."""
    limiter = _SlidingWindowRateLimiter(5, 60, max_clients=8)
    for i in range(1000):
        limiter.check(f"peer-{i}", 100.0 + i * 0.001)
    assert limiter.tracked_clients <= 8


@pytest.mark.req("FRG-NFR-014")
def test_rate_limiter_window_slides():
    """Requests age out of the sliding window, so a client throttled in one
    window is admitted again once the window passes."""
    limiter = _SlidingWindowRateLimiter(2, 10, max_clients=8)
    assert limiter.check("p", 100.0) == (True, 0.0)
    assert limiter.check("p", 100.5)[0] is True
    blocked, retry = limiter.check("p", 101.0)
    assert blocked is False and retry > 0
    # After the oldest stamp (t=100) ages out of the 10s window, room reopens.
    assert limiter.check("p", 111.0)[0] is True


# --------------------------------------------------------------------------
# WebSocket scope is untouched (task 1.2 — timeout enforced on HTTP scope only)
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-014")
async def test_websocket_scope_bypasses_all_http_limits():
    """The middleware runs on the HTTP scope only: a websocket scope is passed
    straight through with its receive/send unchanged, so the request timeout,
    body cap, header cap and rate cap can never touch the long-lived socket
    (which the ws area hardens separately)."""
    captured: dict[str, object] = {}

    async def sentinel(scope, receive, send):
        captured["scope"] = scope
        captured["receive"] = receive
        captured["send"] = send

    # Deliberately hostile limits: 1-byte caps, a sub-millisecond timeout, a
    # rate cap of 1 — none of which may apply to a websocket.
    mw = RequestLimitsMiddleware(
        sentinel,
        max_body_bytes=1,
        max_header_bytes=1,
        request_timeout_seconds=0.001,
        rate_max_requests=1,
        rate_window_seconds=1,
    )
    scope = {
        "type": "websocket",
        "path": "/api/v1/ws",
        "headers": [(b"x-huge", b"y" * 65536)],
        "client": ("10.0.0.1", 5),
    }

    async def receive():
        return {"type": "websocket.connect"}

    async def send(_message):
        return None

    await mw(scope, receive, send)
    assert captured["scope"] is scope
    assert captured["receive"] is receive
    assert captured["send"] is send


# --------------------------------------------------------------------------
# Request-field log sanitization (task 1.3)
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-014")
def test_sanitize_log_field_strips_crlf_and_escapes():
    """CR/LF and ANSI escapes in a request-sourced value collapse to a single
    bounded field — the raw metacharacters never survive to a log line."""
    out = sanitize_log_field("a\r\nINJECTED=forged\x1b[31m evil")
    assert "\n" not in out and "\r" not in out and "\x1b" not in out
    assert "INJECTED" in out  # content preserved, just neutralized


@pytest.mark.req("FRG-NFR-014")
def test_refusal_log_of_crlf_request_field_is_one_escaped_line(caplog):
    """A refusal that names a request path carrying CR/LF logs it as one line,
    with no forged second line (the request-sourced arm of RISK-014)."""
    mw = RequestLimitsMiddleware(
        None,
        max_body_bytes=1,
        max_header_bytes=1,
        request_timeout_seconds=1,
        rate_max_requests=0,
        rate_window_seconds=1,
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/evil\r\nlevel=CRITICAL msg=forged",
        "query_string": b"q=a\r\ninjected=1",
        "headers": [],
        "client": ("1.2.3.4", 9),
    }
    with caplog.at_level(logging.WARNING, logger="foragerr.api.limits"):
        mw._log_refusal(413, "request body too large", scope)
    record = next(r for r in caplog.records if r.name == "foragerr.api.limits")
    message = record.getMessage()
    assert "\n" not in message and "\r" not in message
    assert "forged" in message  # the payload text is present, but inert (no newline)


@pytest.mark.req("FRG-NFR-014")
def test_middleware_refusal_logs_a_clean_single_line_path(caplog):
    """End-to-end: a real refused request logs its path through the sanitizer."""
    with caplog.at_level(logging.WARNING, logger="foragerr.api.limits"):
        with TestClient(_make_app(max_header_bytes=1024)) as client:
            client.get("/ok", headers={"X-Big": "a" * 4000})
    refusals = [r for r in caplog.records if r.name == "foragerr.api.limits"]
    assert refusals, "the 431 refusal should be logged"
    assert all("\n" not in r.getMessage() for r in refusals)
    assert any("path=/ok" in r.getMessage() for r in refusals)


# --------------------------------------------------------------------------
# Middleware coroutine teardown / ASGI-completeness (gate fixes)
# --------------------------------------------------------------------------


def _http_scope() -> dict:
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
        "client": ("1.2.3.4", 9),
    }


@pytest.mark.req("FRG-NFR-014")
async def test_external_cancel_does_not_orphan_the_app_task():
    """If the middleware coroutine is cancelled externally (client disconnect
    before the first response byte, or shutdown) while parked in asyncio.wait,
    the spawned downstream app_task must not be orphaned — the middleware's
    outer finally cancels and awaits it, so no handler keeps running."""
    app_running = asyncio.Event()
    app_finished = asyncio.Event()

    async def hanging_app(scope, receive, send):
        app_running.set()
        try:
            await asyncio.sleep(3600)  # never produces a response
        finally:
            app_finished.set()

    mw = RequestLimitsMiddleware(
        hanging_app,
        max_body_bytes=1024,
        max_header_bytes=16 * 1024,
        request_timeout_seconds=30,  # parks in asyncio.wait, not a fast timeout
        rate_max_requests=0,
        rate_window_seconds=1,
    )

    async def receive():
        await asyncio.sleep(3600)
        return {"type": "http.request", "body": b""}

    async def send(_message):
        return None

    task = asyncio.ensure_future(mw(_http_scope(), receive, send))
    await asyncio.wait_for(app_running.wait(), 1.0)
    await asyncio.sleep(0.02)  # let the middleware settle inside asyncio.wait
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # The orphan would never finish; the finally cancels+awaits it.
    await asyncio.wait_for(app_finished.wait(), 1.0)


@pytest.mark.req("FRG-NFR-014")
async def test_cancel_of_an_already_cancelled_task_does_not_raise():
    """``_cancel`` probing a task the caller already cancelled must not re-raise
    the CancelledError that ``.exception()`` would surface on a cancelled task."""
    async def sleeper():
        await asyncio.sleep(3600)

    task = asyncio.ensure_future(sleeper())
    await asyncio.sleep(0)  # let it start
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    # The guarded done-branch returns cleanly instead of raising.
    await RequestLimitsMiddleware._cancel(task)


@pytest.mark.req("FRG-NFR-014")
async def test_body_cap_after_response_start_propagates_no_silent_hang():
    """A body-cap violation AFTER the response has started cannot be answered
    with a 413 (the response is committed); the middleware must re-raise so the
    server tears the connection down, rather than returning silently and leaving
    an incomplete ASGI response (a protocol hang)."""
    started = asyncio.Event()

    async def start_then_read_app(scope, receive, send):
        await send(
            {"type": "http.response.start", "status": 200, "headers": []}
        )
        started.set()
        # Now read the (over-cap) body: the wrapped receive aborts at the cap.
        while True:
            await receive()

    mw = RequestLimitsMiddleware(
        start_then_read_app,
        max_body_bytes=8,
        max_header_bytes=16 * 1024,
        request_timeout_seconds=0,  # timeout disabled -> straight to await app
        rate_max_requests=0,
        rate_window_seconds=1,
    )

    chunks = iter([{"type": "http.request", "body": b"x" * 100, "more_body": False}])

    async def receive():
        try:
            return next(chunks)
        except StopIteration:
            await asyncio.sleep(3600)
            return {"type": "http.request", "body": b""}

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    # The over-cap body after start propagates rather than hanging silently.
    with pytest.raises(_RequestBodyTooLarge):
        await mw(_http_scope(), receive, send)
    # The response had started; no second (413) response.start was emitted.
    assert sent[0]["type"] == "http.response.start"
    assert sum(1 for m in sent if m["type"] == "http.response.start") == 1
