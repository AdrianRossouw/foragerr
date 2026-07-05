"""Shared helpers for the indexer tests.

Builds a :class:`NewznabClient` / :class:`HttpClientFactory` over an injected
``RecordingTransport`` + ``StubResolver`` so no test performs real DNS or
network traffic, plus small XML fixture builders (valid feeds, caps, error
documents, and the hostile-XML corpus).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import httpx
import pytest

from foragerr.http import HttpClientFactory
from foragerr.indexers import ratelimit
from foragerr.indexers.models import IndexerRow
from foragerr.indexers.newznab import NewznabClient
from foragerr.indexers.repo import serialize_settings
from foragerr.indexers.settings import NewznabSettings
from http_support import PUBLIC_V4, RecordingTransport, StubResolver, make_settings

IDX_HOST = "idx.test"
IDX_BASE = f"https://{IDX_HOST}"
FAKE_KEY = "idx-fake-key-0000"


@pytest.fixture(autouse=True)
def _reset_indexer_gates():
    """Isolate the process-global per-indexer rate gates around every test.

    Lives here (not in a ``conftest.py``) so it never shadows the root
    ``tests/conftest.py`` module — mirroring ``metadata/cv_support.py``'s
    ``_reset_gate``. Import it (noqa F401) into any test module that touches
    the gates."""
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


def make_factory(
    tmp_path: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    host: str = IDX_HOST,
    **overrides: object,
) -> tuple[HttpClientFactory, RecordingTransport]:
    """A factory wired to a recording transport + stub DNS for ``host``."""
    settings = make_settings(tmp_path, **overrides)
    resolver = StubResolver({host: [PUBLIC_V4]})
    transport = RecordingTransport(handler)
    factory = HttpClientFactory(settings, resolver=resolver, transport=transport)
    return factory, transport


def newznab_settings(**overrides: object) -> NewznabSettings:
    payload: dict = {"base_url": IDX_BASE, "api_key": FAKE_KEY}
    payload.update(overrides)
    return NewznabSettings.model_validate(payload)


def make_client(
    tmp_path: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    indexer_id: int = 1,
    min_interval: float = 0.0,
    settings_model: NewznabSettings | None = None,
) -> tuple[NewznabClient, RecordingTransport]:
    factory, transport = make_factory(tmp_path, handler)
    model = settings_model or newznab_settings()
    return (
        NewznabClient(model, factory, indexer_id=indexer_id, min_interval=min_interval),
        transport,
    )


def make_indexer_row(
    *,
    id: int = 1,
    name: str = "TestIndexer",
    priority: int = 25,
    enabled: bool = True,
    enable_rss: bool = True,
    enable_auto: bool = True,
    enable_interactive: bool = True,
    retention_override: int | None = None,
    settings_model: NewznabSettings | None = None,
) -> IndexerRow:
    """An unpersisted ``IndexerRow`` for service/parse tests."""
    import datetime as dt

    model = settings_model or newznab_settings()
    return IndexerRow(
        id=id,
        name=name,
        implementation="newznab",
        protocol="usenet",
        priority=priority,
        enabled=enabled,
        enable_rss=enable_rss,
        enable_auto=enable_auto,
        enable_interactive=enable_interactive,
        settings=serialize_settings(model),
        retention_override=retention_override,
        added_at=dt.datetime(2026, 1, 1),
    )


# --- XML fixtures -----------------------------------------------------------


def newznab_feed(*items: str) -> bytes:
    """A Newznab RSS feed wrapping the given ``<item>`` fragments."""
    body = "".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" '
        'xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">'
        f"<channel>{body}</channel></rss>"
    ).encode()


def feed_item(
    *,
    guid: str,
    title: str,
    url: str = "https://idx.test/nzb/1",
    size: int | None = 52428800,
    pubdate: str = "Wed, 02 Jul 2025 13:00:00 +0000",
    category: int = 7030,
    extra_attrs: dict[str, str] | None = None,
) -> str:
    parts = [
        f"<title>{title}</title>",
        f"<guid>{guid}</guid>",
        f'<enclosure url="{url}" length="{size or 0}" type="application/x-nzb"/>',
        f"<pubDate>{pubdate}</pubDate>",
        f'<newznab:attr name="category" value="{category}"/>',
    ]
    if size is not None:
        parts.append(f'<newznab:attr name="size" value="{size}"/>')
    for name, value in (extra_attrs or {}).items():
        parts.append(f'<newznab:attr name="{name}" value="{value}"/>')
    return f"<item>{''.join(parts)}</item>"


def error_doc(code: int, description: str = "error") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<error code="{code}" description="{description}"/>'
    ).encode()


def caps_doc() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<caps>"
        '<limits max="100" default="75"/>'
        "<searching>"
        '<search available="yes" supportedParams="q"/>'
        '<book-search available="yes" supportedParams="q"/>'
        "</searching>"
        "<categories>"
        '<category id="7000" name="Books">'
        '<subcat id="7030" name="Comics"/>'
        "</category>"
        "</categories>"
        "</caps>"
    ).encode()


# --- hostile XML corpus (FRG-SEC-002) --------------------------------------

BILLION_LAUGHS = (
    b'<?xml version="1.0"?>'
    b"<!DOCTYPE lolz [<!ENTITY lol \"lol\">"
    b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
    b'<!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">'
    b"]><lolz>&lol4;</lolz>"
)

EXTERNAL_ENTITY = (
    b'<?xml version="1.0"?>'
    b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
    b"<rss><channel><item><title>&xxe;</title></item></channel></rss>"
)

QUADRATIC_BLOWUP = (
    b'<?xml version="1.0"?>'
    b'<!DOCTYPE bomb [<!ENTITY a "' + b"a" * 5000 + b'">]>'
    b"<bomb>" + b"&a;" * 200 + b"</bomb>"
)

JUNK_BYTES = b"\x00\x01 this is not xml at all <<< &&& >>>"
