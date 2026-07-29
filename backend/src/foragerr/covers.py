"""Cover-URL allowlist rules and evaluation (FRG-META-021).

The single, dependency-free source of truth for which cover URLs foragerr may
fetch or store. Imported by the same-origin cover proxy (its request-time
check and its per-redirect-hop check) and by the pull ingest (fail-closed
validation and canonicalization of source-supplied cover URLs). It sits below
both the API and the domain packages so neither depends on the other for this
security-sensitive control.

The two public entry points are **total** — they never raise, whatever the
input — because they are the trust boundary for a client-supplied URL: a
malformed authority must fail closed to a refusal, never surface as a 500 or
abort a pull run.

Rule shape: a target must satisfy one :data:`COVER_HOST_RULES` entry — a host,
a subdomain policy, and an optional required path prefix (directory-boundary).
A shared/multi-tenant endpoint (``s3.amazonaws.com``) MUST be exact-host with a
required prefix — host alone would authorize every tenant on it, and its
objects also resolve virtual-hosted at ``comicgeeks.s3.amazonaws.com``, which a
subdomain policy would let sidestep the prefix. Beyond the host/prefix rules,
every target is additionally held to: HTTPS only, no userinfo, the default TLS
port only, an ASCII host (so ``str.lower`` here cannot desync from the client's
IDNA/UTS-46 host parsing), and a path with no dot-segment, no ``..``-prefixed
segment, no backslash, and no control/bidi character — traversal and lookalikes
are refused outright, never normalized away.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import SplitResult, unquote, urlsplit, urlunsplit

from foragerr.metadata.sanitize import _BIDI_INVISIBLE_RE


@dataclass(frozen=True)
class CoverHostRule:
    """One allowlist entry: which host, whether its subdomains count, and the
    path prefix (directory-boundary) a target on that host must sit under."""

    host: str
    allow_subdomains: bool
    required_prefix: str | None = None


#: Hosts covers may be fetched from. Grows per-host by change, never by config.
#: A shared/multi-tenant endpoint MUST be exact-host with a required prefix.
COVER_HOST_RULES: tuple[CoverHostRule, ...] = (
    CoverHostRule("comicvine.gamespot.com", allow_subdomains=True),
    CoverHostRule("comicvine.com", allow_subdomains=True),
    CoverHostRule(
        "s3.amazonaws.com", allow_subdomains=False, required_prefix="/comicgeeks/"
    ),
)

#: A stored/served cover URL is refused past this length — the proxy's own
#: ``src`` query cap is 1024, so a longer URL could never be fetched anyway and
#: must not be persisted (a permanently broken cover, and unbounded storage).
MAX_COVER_URL_LENGTH = 1024

#: Encoding layers peeled when testing a segment for traversal. Peeling is
#: refusal-only — extra layers can only make the test stricter.
_MAX_DECODE_PEELS = 4

#: Control characters (C0/DEL, incl. CR/LF) — a cover URL carrying any is
#: refused, so nothing control-laden is ever stored or logged as a fetch target.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _segment_is_clean(segment: str) -> bool:
    """False if a single path segment is (or decodes at any bounded depth to) a
    dot-segment, a ``..``-prefixed segment (``..;`` and path-parameter tricks),
    or carries a backslash. Percent-escapes that do not decode cleanly (overlong
    UTF-8 such as ``%c0%ae``) are themselves refused rather than replaced."""
    candidate = segment
    for _ in range(_MAX_DECODE_PEELS):
        if candidate == "." or candidate.startswith("..") or "\\" in candidate:
            return False
        try:
            peeled = unquote(candidate, errors="strict")
        except UnicodeDecodeError:
            return False
        if peeled == candidate:
            break
        candidate = peeled
    return True


def _path_is_clean(path: str) -> bool:
    if _CONTROL_RE.search(path) or _BIDI_INVISIBLE_RE.search(path):
        return False
    return all(_segment_is_clean(segment) for segment in path.split("/"))


def target_allowed(
    scheme: str,
    host: str,
    path: str,
    *,
    userinfo_present: bool = False,
    port: int | None = None,
    ascii_host: bool = True,
) -> bool:
    """Rule evaluation over already-split parts. ``path`` is the path as sent
    (still percent-encoded); it is decoded exactly once for the prefix test.
    Used by both the request-time check (via :func:`cover_url_allowed`) and the
    proxy's per-hop redirect check over an ``httpx.URL``."""
    if scheme != "https" or not host or userinfo_present or not ascii_host:
        return False
    if port not in (None, 443):
        return False
    host = host.lower()
    decoded = unquote(path) or "/"
    if not decoded.startswith("/") or not _path_is_clean(path):
        return False
    for rule in COVER_HOST_RULES:
        if host != rule.host and not (
            rule.allow_subdomains and host.endswith("." + rule.host)
        ):
            continue
        if rule.required_prefix and not decoded.startswith(rule.required_prefix):
            continue
        return True
    return False


def _split(url: str) -> SplitResult | None:
    """``urlsplit`` that never raises and never returns a URL whose port is
    malformed — either yields a usable split or ``None``."""
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - forces the lazy ValueError on a bad port here
    except ValueError:
        return None
    return parts


def _allowed_parts(parts: SplitResult) -> bool:
    host = parts.hostname or ""
    return target_allowed(
        parts.scheme,
        host,
        parts.path,
        userinfo_present=bool(parts.username or parts.password),
        port=parts.port,
        ascii_host=host.isascii(),
    )


def cover_url_allowed(url: str) -> bool:
    """May foragerr fetch this cover URL? (FRG-META-021) Total — a malformed
    URL is a refusal, never an exception. The single source of truth shared by
    the request-time check, the per-hop redirect check, and the pull ingest."""
    parts = _split(url)
    return parts is not None and _allowed_parts(parts)


def canonical_cover_url(url: str) -> str | None:
    """The stored/fetched form of a source cover URL, or ``None`` if it is not
    allowed. Total. Rebuilds from the validated host and path only — userinfo,
    port, query (the source's volatile cache-buster), and fragment are dropped,
    so one image has one canonical form (idempotent storage per FRG-PULL-003, a
    stable proxy cache key, no fetch multiplication) and the byte-identical path
    is preserved (no decoded rebuild). Refused past :data:`MAX_COVER_URL_LENGTH`.
    """
    parts = _split((url or "").strip())
    if parts is None or not _allowed_parts(parts):
        return None
    canonical = urlunsplit(("https", (parts.hostname or "").lower(), parts.path, "", ""))
    if not canonical or len(canonical) > MAX_COVER_URL_LENGTH:
        return None
    return canonical
