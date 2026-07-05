"""Shared helpers for the DDL (GetComics) tests.

Builds an :class:`HttpClientFactory` over an injected ``RecordingTransport`` +
``StubResolver`` (no test performs real DNS or network traffic) and a small
``FakeSite`` that serves recorded GetComics search/post HTML and controllable
file-download responses (Range honored / ignored / mismatched, missing/ wrong
Content-Length, redirect-to-private, off-allowlist redirect). All provider hosts
resolve to a PUBLIC TEST-NET address so the ``external`` egress profile is
genuinely exercised; private/off-allowlist targets are the negative cases.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from typing import AsyncIterator, Callable

# Ensure the tests root (http_support.py) is importable when running only
# tests/ddl in isolation (prepend import mode only adds the test file's dir).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from foragerr.http import HttpClientFactory  # noqa: E402
from http_support import PUBLIC_V4, RecordingTransport, StubResolver, make_settings  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: Every host a DDL test might reach, resolved to a public TEST-NET address.
DDL_HOSTS = {
    "getcomics.org": [PUBLIC_V4],
    "getcomics.info": [PUBLIC_V4],
    "comicfiles.ru": [PUBLIC_V4],
    "evil.example": [PUBLIC_V4],  # off-allowlist but publicly resolvable
    "mega.nz": [PUBLIC_V4],
    "pixeldrain.com": [PUBLIC_V4],
}


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_factory(
    tmp_path: Path, handler: Callable[[httpx.Request], httpx.Response]
) -> tuple[HttpClientFactory, RecordingTransport]:
    settings = make_settings(tmp_path)
    resolver = StubResolver(DDL_HOSTS)
    transport = RecordingTransport(handler)
    factory = HttpClientFactory(settings, resolver=resolver, transport=transport)
    return factory, transport


# --- response builders (full control over headers for the size scenarios) ----


async def _agen(body: bytes, chunk: int = 65536) -> AsyncIterator[bytes]:
    for i in range(0, max(len(body), 1), chunk):
        yield body[i : i + chunk]


def resp_full(body: bytes) -> httpx.Response:
    """200 with an exact Content-Length (bytes content auto-sets it)."""
    return httpx.Response(200, content=body)


def resp_range(body: bytes, start: int) -> httpx.Response:
    """206 honoring a Range from ``start`` with a matching Content-Range."""
    part = body[start:]
    return httpx.Response(
        206,
        headers={"content-range": f"bytes {start}-{len(body) - 1}/{len(body)}"},
        content=part,
    )


def resp_range_mismatch(body: bytes, requested: int, claimed: int) -> httpx.Response:
    """206 whose Content-Range offset does NOT match the requested offset."""
    return httpx.Response(
        206,
        headers={"content-range": f"bytes {claimed}-{len(body) - 1}/{len(body)}"},
        content=body[requested:],
    )


def resp_missing_cl(body: bytes) -> httpx.Response:
    """200 with NO Content-Length (streamed/chunked)."""
    return httpx.Response(200, content=_agen(body))


def resp_wrong_cl(body: bytes, declared: int) -> httpx.Response:
    """200 declaring a Content-Length that the body does not satisfy."""
    return httpx.Response(
        200, headers={"content-length": str(declared)}, content=_agen(body)
    )


def redirect(location: str) -> httpx.Response:
    return httpx.Response(302, headers={"location": location})


# --- a valid CBZ (zip with an image entry, above the size floor) -------------


def make_cbz(pad: int = 30_000) -> bytes:
    """A real zip carrying one image entry, comfortably above the size floor."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * pad)
    return buffer.getvalue()


def make_zip_without_image(pad: int = 30_000) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("readme.txt", b"not an image" + b"\x00" * pad)
    return buffer.getvalue()


def make_pdf(pad: int = 30_000) -> bytes:
    return b"%PDF-1.7\n" + b"0" * pad


__all__ = [
    "DDL_HOSTS",
    "FIXTURES",
    "fixture",
    "make_cbz",
    "make_factory",
    "make_pdf",
    "make_zip_without_image",
    "redirect",
    "resp_full",
    "resp_missing_cl",
    "resp_range",
    "resp_range_mismatch",
    "resp_wrong_cl",
]
