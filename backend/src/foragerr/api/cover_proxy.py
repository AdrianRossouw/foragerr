"""Same-origin proxy for metadata covers (FRG-META-021).

The v0.9.17 SPA Content-Security-Policy (`img-src 'self' data: blob:`,
FRG-SEC-006) is deliberately self-contained — so covers from the metadata
sources (ComicVine candidates in the Add-series picker and Library-import
proposals; LOCG covers on the pull/Calendar surfaces) cannot be hotlinked.
This endpoint fetches them server-side and serves them same-origin instead,
keeping the CSP untouched.

SSRF posture, layered (FRG-PROC-006 — this is a client-supplied-URL fetch,
the most abuse-prone endpoint shape there is):

1. **Perimeter**: the route lives under ``/api/v1`` — default-deny auth
   applies; anonymous callers never reach the fetch logic.
2. **Allowlist rules**: HTTPS-only, and the target must satisfy one
   :data:`COVER_HOST_RULES` entry — a host, a subdomain policy, and an
   optional required path prefix. Two sources are allowed today:

   - the ComicVine media hosts, exact or dot-boundary subdomain, no path
     constraint (``evilcomicvine.gamespot.com.evil`` shapes can't ride the
     suffix);
   - the LOCG cover store, which lives path-style under ``/comicgeeks/`` on
     the SHARED endpoint ``s3.amazonaws.com``. A host-only entry there would
     turn this endpoint into a proxy for every public S3 bucket on the
     internet, so the rule is exact-host (no subdomain form — the same
     objects also resolve virtual-hosted at ``comicgeeks.s3.amazonaws.com``,
     which would sidestep any path constraint) plus a required prefix
     matched on a directory boundary.

   One evaluator, :func:`foragerr.covers.cover_url_allowed`, is the single
   source of truth: the request-time check, the per-hop redirect check, and
   the pull ingest's fail-closed cover validation all run the same rules. It
   is total — a malformed URL fails closed to a refusal, never a 500.
3. **Path & authority handling** (:mod:`foragerr.covers`): the path is
   percent-decoded ONCE for the prefix test and refused outright if a
   dot-segment, ``..``-prefixed segment, backslash, or control/bidi character
   survives — traversal is never normalized away. Userinfo, a non-default
   port, and a non-ASCII host are refused too, so no caller can multiply
   fetches or dial an arbitrary port through the allowlist, and the fetched
   path is always the caller's wire form, never a decoded rebuild.
4. **Egress validation**: the fetch uses the hardened outbound factory's
   ``external`` profile — per-hop SSRF checks (loopback/private/link-local
   refused even via DNS tricks), TLS verified, bounded redirects with the
   hop re-check.
5. **Content verification**: magic-byte sniff BEFORE any byte is served —
   JPEG/PNG/GIF/WebP only; an HTML error page or JSON body never reaches
   the browser as an "image".
6. **Bounds**: streaming size cap; bounded in-memory LRU so the cache
   itself cannot grow without limit.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict

from fastapi import APIRouter, Query, Request, Response

from foragerr.api.errors import ApiError
from foragerr.covers import canonical_cover_url, cover_hop_allowed
from foragerr.http import HttpClientFactory

logger = logging.getLogger("foragerr.api.cover_proxy")

router = APIRouter(prefix="/metadata", tags=["metadata"])


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


def _hop_check(url) -> None:
    """Per-hop validator handed to the factory: every hop of the redirect walk
    — not just the first URL — is re-evaluated against the same rules (in
    :mod:`foragerr.covers`, which owns the wire-form extraction), so a hop to
    another host, to a non-default port, or to a shared-host path outside the
    required prefix is refused mid-flight."""
    if not cover_hop_allowed(url):
        host = getattr(url, "host", "") or ""
        raise ValueError(f"cover hop {host!r} is outside the cover allowlist")


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


#: Concurrent upstream fetches: the listener rate cap already bounds
#: per-client request rates, but a burst of DISTINCT cover URLs
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
    # canonical_cover_url is total and is both the gate and the cache key: a
    # malformed or off-allowlist src fails closed to this 400 (never an
    # unguarded urlsplit ValueError / 500), and the canonical form drops
    # userinfo, port, query, and fragment so variant spellings of one image
    # share one cache entry and can't multiply fetches. The path is preserved
    # byte-for-byte, so the FETCHED url stays the caller's wire form
    # (decode-once discipline), never a rebuild.
    cache_key = canonical_cover_url(src)
    if cache_key is None:
        raise ApiError(
            400,
            "cover src is not an allowed metadata cover target "
            "(host, subdomain, port, or path prefix)",
            field="src",
        )

    cached = _cache.get(cache_key)
    if cached is not None:
        _cache.move_to_end(cache_key)
        body, content_type = cached
    else:
        client = HttpClientFactory(request.app.state.settings).external()
        try:
            # The factory enforces the byte cap, TLS, per-hop SSRF egress
            # checks, and the bounded redirect walk (FRG-SEC-001/NFR-006).
            # hop_check additionally re-runs the allowlist rules on EVERY hop
            # — including redirect targets: an allowlisted URL that 302s to
            # another public host, or to a shared-host path outside the
            # required prefix, is refused rather than followed (the egress
            # policy alone would allow any public host).
            async with _semaphore():
                result = await client.get(
                    src, max_bytes=MAX_COVER_BYTES, hop_check=_hop_check
                )
        except Exception as exc:  # noqa: BLE001 - upstream fetch boundary
            logger.info("cover proxy fetch failed: %s", exc)
            raise ApiError(502, "cover fetch failed") from exc
        finally:
            await client.aclose()
        if result.status_code != 200:
            raise ApiError(502, f"cover upstream answered {result.status_code}")
        body = result.content
        content_type = _sniff_image(body) or ""
        if not content_type:
            raise ApiError(502, "cover response is not an image")
        _cache_put(cache_key, body, content_type)

    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )
