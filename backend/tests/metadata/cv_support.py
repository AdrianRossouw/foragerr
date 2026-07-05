"""Shared fixtures/helpers for the ComicVine metadata tests.

Every test resets the process-global rate gate so timing/degraded state never
leaks between tests, and builds a :class:`ComicVineClient` over an injected
``RecordingTransport`` + ``StubResolver`` so no test performs real DNS or
network traffic (the single live smoke test in ``test_live.py`` is the sole,
env-gated exception).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import httpx
import pytest

from foragerr.http import HttpClientFactory
from foragerr.metadata import ratelimit
from foragerr.metadata.comicvine import DEFAULT_BASE, ComicVineClient
from http_support import PUBLIC_V4, RecordingTransport, StubResolver, make_settings

CV_HOST = "comicvine.gamespot.com"


@pytest.fixture(autouse=True)
def _reset_gate():
    """Isolate the process-global rate gate around every test."""
    ratelimit.reset_gate()
    yield
    ratelimit.reset_gate()


def json_response(payload: object, *, status: int = 200) -> httpx.Response:
    """A 200 JSON httpx response from a dict/list payload."""
    return httpx.Response(status, content=json.dumps(payload).encode())


def make_client(
    tmp_path: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    **overrides: object,
) -> tuple[ComicVineClient, RecordingTransport]:
    """Build a ComicVineClient wired to a recording transport + stub DNS.

    ``overrides`` are Settings overrides (e.g. ``comicvine_min_interval_seconds``).
    A sensible fast default interval keeps timing tests snappy unless the test
    is specifically exercising the interval.
    """
    overrides.setdefault("comicvine_api_key", "CV-SECRET-KEY-abc123")
    overrides.setdefault("comicvine_min_interval_seconds", 0.4)
    settings = make_settings(tmp_path, **overrides)
    resolver = StubResolver({CV_HOST: [PUBLIC_V4]})
    transport = RecordingTransport(handler)
    factory = HttpClientFactory(settings, resolver=resolver, transport=transport)
    return ComicVineClient(settings, factory, base=DEFAULT_BASE), transport
