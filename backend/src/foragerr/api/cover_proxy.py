"""Same-origin proxy for metadata candidate covers (FRG-META-021).

The v0.9.17 SPA Content-Security-Policy (`img-src 'self' data: blob:`,
FRG-SEC-006) is deliberately self-contained — so candidate covers from
ComicVine (Add-series picker, Library-import proposals) cannot be hotlinked.
This endpoint fetches them server-side and serves them same-origin instead,
keeping the CSP untouched.

SSRF posture, layered (FRG-PROC-006 — this is a client-supplied-URL fetch,
the most abuse-prone endpoint shape there is):

1. **Perimeter**: the route lives under ``/api/v1`` — default-deny auth
   applies; anonymous callers never reach the fetch logic.
2. **Host allowlist**: HTTPS-only, host must be a ComicVine media host
   (exact or dot-boundary subdomain — ``evilcomicvine.gamespot.com.evil``
   shapes can't ride the suffix).
3. **Egress validation**: the fetch uses the hardened outbound factory's
   ``external`` profile — per-hop SSRF checks (loopback/private/link-local
   refused even via DNS tricks), TLS verified, bounded redirects with the
   hop re-check.
4. **Content verification**: magic-byte sniff BEFORE any byte is served —
   JPEG/PNG/GIF/WebP only; an HTML error page or JSON body never reaches
   the browser as an "image".
5. **Bounds**: streaming size cap; bounded in-memory LRU so the cache
   itself cannot grow without limit.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Request, Response

from foragerr.api.errors import ApiError
from foragerr.http import HttpClientFactory

logger = logging.getLogger("foragerr.api.cover_proxy")

router = APIRouter(prefix="/metadata", tags=["metadata"])

#: ComicVine media hosts candidate covers are served from. Exact host or
#: dot-boundary subdomain; grows per-host by change, never by config.
COVER_HOSTS: frozenset[str] = frozenset({"comicvine.gamespot.com", "comicvine.com"})

#: Streaming byte cap — CV covers are tens to a few hundred KiB; 2 MiB is
#: generous headroom, never a whole-archive accident.
MAX_COVER_BYTES = 2 * 1024 * 1024

#: Bounded proxy cache: picker sessions re-request the same dozen covers.
_CACHE_CAPACITY = 64

#: (magic prefix, content type) — sniffed, never trusted from the remote.
_IMAGE_MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()


def _host_allowed(host: str) -> bool:
    host = host.lower()
    return any(host == h or host.endswith("." + h) for h in COVER_HOSTS)


def _hop_check(url) -> None:
    """Per-hop validator handed to the factory: every hop of the redirect
    walk — not just the first URL — must stay on the cover allowlist."""
    scheme = getattr(url, "scheme", "")
    host = getattr(url, "host", "") or ""
    if scheme != "https" or not _host_allowed(host):
        raise ValueError(
            f"cover hop {host!r} (scheme {scheme!r}) is outside the cover allowlist"
        )


def _sniff_image(body: bytes) -> str | None:
    for magic, content_type in _IMAGE_MAGICS:
        if body.startswith(magic):
            return content_type
    # WebP: RIFF....WEBP
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    return None


def _cache_put(url: str, body: bytes, content_type: str) -> None:
    _cache[url] = (body, content_type)
    _cache.move_to_end(url)
    while len(_cache) > _CACHE_CAPACITY:
        _cache.popitem(last=False)


def reset_cache() -> None:
    """Test hook: drop all cached covers."""
    _cache.clear()


#: Concurrent upstream fetches (Codex hardening note): the listener rate cap
#: already bounds per-client request rates, but a burst of DISTINCT cover URLs
#: from one authenticated picker session shouldn't fan out unboundedly either.
_fetch_semaphore: "asyncio.Semaphore | None" = None


def _semaphore() -> "asyncio.Semaphore":
    global _fetch_semaphore
    if _fetch_semaphore is None:
        _fetch_semaphore = asyncio.Semaphore(4)
    return _fetch_semaphore


@router.get("/cover")
async def proxy_cover(request: Request, src: str = Query(..., max_length=1024)) -> Response:
    """Fetch one allowlisted cover and serve it same-origin (FRG-META-021)."""
    parts = urlsplit(src)
    if parts.scheme != "https":
        raise ApiError(400, "cover src must be https", field="src")
    if not parts.hostname or not _host_allowed(parts.hostname):
        raise ApiError(400, "cover src host is not an allowed metadata host", field="src")
    # Canonical cache/fetch key (Codex hardening note): case-normalized
    # scheme+host, fragment dropped — variant spellings of one URL share one
    # cache entry and can't multiply fetches.
    src = parts._replace(
        scheme="https", netloc=(parts.netloc or "").lower(), fragment=""
    ).geturl()

    cached = _cache.get(src)
    if cached is not None:
        _cache.move_to_end(src)
        body, content_type = cached
    else:
        client = HttpClientFactory(request.app.state.settings).external()
        try:
            # The factory enforces the byte cap, TLS, per-hop SSRF egress
            # checks, and the bounded redirect walk (FRG-SEC-001/NFR-006).
            # hop_check additionally pins EVERY hop — including redirect
            # targets — to the cover allowlist: a CV URL that 302s to a
            # non-CV public host is refused, not followed (the egress policy
            # alone would allow any public host).
            async with _semaphore():
                result = await client.get(
                    src, max_bytes=MAX_COVER_BYTES, hop_check=_hop_check
                )
        except Exception as exc:  # noqa: BLE001 - upstream fetch boundary
            logger.info("cover proxy fetch failed for %s: %s", parts.hostname, exc)
            raise ApiError(502, "cover fetch failed") from exc
        finally:
            await client.aclose()
        if result.status_code != 200:
            raise ApiError(502, f"cover upstream answered {result.status_code}")
        body = result.content
        content_type = _sniff_image(body) or ""
        if not content_type:
            raise ApiError(502, "cover response is not an image")
        _cache_put(src, body, content_type)

    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )
