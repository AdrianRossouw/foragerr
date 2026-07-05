"""Shared helpers for the download-client (SABnzbd) tests.

Builds a :class:`SabnzbdClient` over an injected ``RecordingTransport`` +
``StubResolver`` so no test performs real DNS or network traffic, plus a
recorded SABnzbd fixture API (``mode=version``/``get_config``/``queue``/
``history``/``addfile``) and NZB fixture builders (valid / empty / segment-less).

The SAB base URL is a deliberately PRIVATE address so a test that succeeds
proves the ``local-service`` egress profile is in use (the ``external`` profile
would refuse an RFC-1918 host); the indexer NZB host resolves to a public
TEST-NET address through the stub resolver.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import httpx

from foragerr.downloads.clients.sabnzbd import SabnzbdClient
from foragerr.downloads.pathmap import RemotePathMapping
from foragerr.downloads.settings import SabnzbdSettings
from foragerr.http import HttpClientFactory
from foragerr.providers.backoff import ProviderBackoff
from http_support import PUBLIC_V4, RecordingTransport, StubResolver, make_settings

#: The indexer host NZB bytes are fetched from (external profile).
IDX_HOST = "idx.test"
NZB_URL = f"https://{IDX_HOST}/nzb/1"
#: A PRIVATE SAB host — reachable only under the local-service profile.
SAB_BASE = "http://10.1.2.3:8080"
FAKE_SAB_KEY = "sab-fake-key-0000"


# --- NZB fixtures -----------------------------------------------------------

VALID_NZB = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">'
    b'<file poster="p" date="1700000000" subject="Comic 001 (2024)">'
    b"<groups><group>alt.binaries.comics</group></groups>"
    b'<segments><segment bytes="500000" number="1">abc123@news</segment>'
    b"</segments></file></nzb>"
)

#: Well-formed NZB XML but with no <segment> — must fail validation.
NO_SEGMENT_NZB = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">'
    b'<file poster="p" date="1" subject="s">'
    b"<groups><group>alt.binaries.comics</group></groups>"
    b"</file></nzb>"
)

JUNK_NZB = b"\x00 this is not xml <<< &&&"
EMPTY_NZB = b""


# --- recorded SABnzbd fixture API -------------------------------------------


def sab_version() -> dict[str, Any]:
    return {"version": "4.3.2"}


def sab_get_config(*, categories: tuple[str, ...] = ("comics", "movies")) -> dict[str, Any]:
    return {
        "config": {
            "categories": [{"name": name} for name in categories],
            "misc": {"complete_dir": "/downloads/complete"},
        }
    }


def queue_slot(
    *,
    nzo_id: str,
    filename: str = "Comic 001 (2024)",
    cat: str = "comics",
    status: str = "Downloading",
    mb: str = "50.0",
    mbleft: str = "20.0",
    timeleft: str = "0:01:30",
) -> dict[str, Any]:
    return {
        "nzo_id": nzo_id,
        "filename": filename,
        "cat": cat,
        "status": status,
        "mb": mb,
        "mbleft": mbleft,
        "timeleft": timeleft,
        "percentage": "60",
    }


def history_slot(
    *,
    nzo_id: str,
    name: str = "Comic 001 (2024)",
    category: str = "comics",
    status: str = "Completed",
    bytes_: int = 52_428_800,
    fail_message: str = "",
    storage: str = "/downloads/complete/Comic 001 (2024)",
) -> dict[str, Any]:
    return {
        "nzo_id": nzo_id,
        "name": name,
        "category": category,
        "status": status,
        "bytes": bytes_,
        "fail_message": fail_message,
        "storage": storage,
    }


class SabFixture:
    """A recorded SABnzbd API + indexer NZB endpoint served over one transport.

    Attributes set per-test control each ``mode``'s response; ``requests`` and
    ``modes`` record what the client actually issued so contract tests can assert
    the wire behavior (server-side fetch, category filter, addfile, etc.).
    """

    def __init__(self) -> None:
        self.version_doc: dict[str, Any] = sab_version()
        self.config_doc: dict[str, Any] = sab_get_config()
        self.queue_slots: list[dict[str, Any]] = []
        self.history_slots: list[dict[str, Any]] = []
        self.addfile_nzo_ids: list[str] = ["SABnzbd_nzo_abc123"]
        self.nzb_bytes: bytes = VALID_NZB
        self.nzb_status: int = 200
        self.sab_status: int = 200
        self.requests: list[httpx.Request] = []
        self.modes: list[str] = []

    def handler(self) -> Callable[[httpx.Request], httpx.Response]:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            host = (request.url.host or "").lower()
            if host == IDX_HOST:  # server-side NZB fetch (external profile)
                if self.nzb_status != 200:
                    return httpx.Response(self.nzb_status)
                return httpx.Response(200, content=self.nzb_bytes)
            # SABnzbd API (local-service profile)
            if self.sab_status != 200:
                return httpx.Response(self.sab_status)
            mode = request.url.params.get("mode", "")
            self.modes.append(mode)
            return httpx.Response(200, json=self._sab_body(mode))

        return handle

    def _sab_body(self, mode: str) -> dict[str, Any]:
        if mode == "version":
            return self.version_doc
        if mode == "get_config":
            return self.config_doc
        if mode == "queue":
            return {"queue": {"slots": list(self.queue_slots)}}
        if mode == "history":
            return {"history": {"slots": list(self.history_slots)}}
        if mode == "addfile":
            return {"status": True, "nzo_ids": list(self.addfile_nzo_ids)}
        return {"status": True}


def sab_settings(**overrides: Any) -> SabnzbdSettings:
    payload: dict[str, Any] = {"base_url": SAB_BASE, "api_key": FAKE_SAB_KEY}
    payload.update(overrides)
    return SabnzbdSettings.model_validate(payload)


def make_sab_factory(
    tmp_path: Path, fixture: SabFixture
) -> tuple[HttpClientFactory, RecordingTransport]:
    """A factory wired to the fixture's transport + a stub resolver for idx.test."""
    settings = make_settings(tmp_path)
    resolver = StubResolver({IDX_HOST: [PUBLIC_V4]})
    transport = RecordingTransport(fixture.handler())
    factory = HttpClientFactory(settings, resolver=resolver, transport=transport)
    return factory, transport


def make_sab_client(
    tmp_path: Path,
    fixture: SabFixture,
    db,
    *,
    client_id: int = 1,
    mappings: list[RemotePathMapping] | None = None,
    remove_completed_downloads: bool = True,
    settings_model: SabnzbdSettings | None = None,
) -> SabnzbdClient:
    """A :class:`SabnzbdClient` over the fixture, with a live back-off ladder."""
    factory, _ = make_sab_factory(tmp_path, fixture)
    model = settings_model or sab_settings()
    return SabnzbdClient(
        model,
        factory,
        backoff=ProviderBackoff(db),
        client_id=client_id,
        mappings=mappings,
        remove_completed_downloads=remove_completed_downloads,
    )


def parse_json(content: bytes) -> Any:
    return json.loads(content)
