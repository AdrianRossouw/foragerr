"""DDL file download execution: streaming, resume, size accounting, safe names,
and the per-provider outbound allowlist (FRG-DDL-008/009/011/012).

Every deliberate divergence from mylar-ddl's download path lives here:

- **streaming** ≥64 KiB chunks into ``<config>/ddl-staging/<id>.partial`` with
  byte accounting against the expected size (search result or Content-Length);
  a response lacking a usable Content-Length after one retry, or a final size
  that mismatches the expected beyond tolerance, fails the attempt — Mylar's
  1 KiB chunks + display-only size (§3.4/§3.6) are the anti-pattern;
- **safe resume** (FRG-DDL-009): a Range request is trusted ONLY on a ``206``
  whose ``Content-Range`` offset matches the local partial; any ``200`` (full
  body) or offset mismatch restarts from zero, never appends (Mylar's §3.5
  resume-trust flaw);
- **safe filenames** (FRG-DDL-011, SECURITY-mandatory): the final name is
  ``{series} {issue} [__{issueid}__]{ext}`` built from library metadata + the
  queue id via ``safe_path_component`` — NEVER from a redirect-final URL or a
  ``Content-Disposition`` header;
- **outbound allowlist** (FRG-DDL-012, SECURITY-mandatory): a per-provider
  scheme+host allowlist re-validated on EVERY redirect hop (passed to the HTTP
  factory's streaming ``hop_check``), on top of the always-on SSRF egress policy
  and TLS verification the factory guarantees.

No ``httpx`` import here — all traffic goes through the shared HTTP factory (the
FRG-NFR-006 choke point / static-guard); the hop callback reads only ``.scheme``
/``.host`` off the URL object the factory hands it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from foragerr.ddl.errors import DdlDownloadError, OutboundNotAllowedError
from foragerr.http import HttpClientFactory, OutboundHttpError
from foragerr.security.paths import safe_path_component

logger = logging.getLogger("foragerr.ddl.download")

#: Streaming chunk size — ≥64 KiB (FRG-DDL-008; Mylar's 1 KiB is §3.6).
CHUNK_SIZE = 64 * 1024

#: Tolerance when the expected size comes from the *search result* (an
#: approximate, human-rounded "45 MB"); a Content-Length is treated as exact.
SEARCH_SIZE_TOLERANCE = 0.25

#: GetComics download hosts allowed in addition to the provider's own host
#: (its main-server/mirror links redirect through these). Mirror-host *adapters*
#: (Mega/MediaFire/Pixeldrain) are backlog B and never reach here.
KNOWN_DDL_HOSTS: frozenset[str] = frozenset(
    {"getcomics.org", "getcomics.info", "comicfiles.ru", "readcomicsonline.ru"}
)


@dataclass(frozen=True, slots=True)
class AllowList:
    """A per-provider scheme+host allowlist (FRG-DDL-012)."""

    hosts: frozenset[str]
    scheme: str = "https"

    def allows(self, url: str) -> bool:
        """Whether ``url``'s scheme+host is on the allowlist (parses the URL)."""
        parts = urlsplit(url)
        return self._allows(parts.scheme, (parts.hostname or "").lower())

    def allows_parts(self, scheme: str, host: str) -> bool:
        """Whether a pre-split ``scheme``/``host`` pair is on the allowlist.

        Used by the streaming ``hop_check`` (which is handed the scheme/host off
        each redirect hop's URL object) so no URL re-parse is needed per hop."""
        return self._allows(scheme, (host or "").lower())

    def _allows(self, scheme: str, host: str) -> bool:
        if scheme != self.scheme or not host:
            return False
        return any(host == h or host.endswith("." + h) for h in self.hosts)


def build_allowlist(base_url: str) -> AllowList:
    """The allowlist for a GetComics provider: its own host + known DDL hosts."""
    base_host = (urlsplit(base_url).hostname or "").lower()
    hosts = set(KNOWN_DDL_HOSTS)
    if base_host:
        hosts.add(base_host)
    return AllowList(hosts=frozenset(hosts))


def _hop_check(allowlist: AllowList):
    """A factory ``hop_check`` closure: refuse any hop off the allowlist.

    Reads only ``.scheme``/``.host`` off the URL the factory passes (an
    ``httpx.URL``) so this module never imports httpx (FRG-NFR-006)."""

    def check(url) -> None:
        scheme = getattr(url, "scheme", "")
        host = getattr(url, "host", "") or ""
        if not allowlist.allows_parts(scheme, host):
            raise OutboundNotAllowedError(
                f"outbound host {host!r} (scheme {scheme!r}) is outside the "
                "provider allowlist"
            )

    return check


def build_hop_check(allowlist: AllowList):
    """Public per-provider hop validator (FRG-DDL-012).

    Used by the file download (streaming ``hop_check``) AND by the scraped-page
    link-resolution fetches (post page + search page) so EVERY DDL HTTP fetch —
    not just the file transfer — enforces the provider scheme+host allowlist on
    every redirect hop, on top of the always-on SSRF egress policy."""
    return _hop_check(allowlist)


def safe_output_name(
    *,
    series_title: str | None,
    issue_number: str | None,
    issue_id: int | None,
    queue_id: int,
    ext: str,
    fallback_title: str | None = None,
) -> str:
    """Build the system-generated safe file name (FRG-DDL-011).

    ``{series} {issue} [__{issueid}__]{ext}`` — every variable component is
    reduced with :func:`safe_path_component` (path separators neutralized,
    traversal erased, reserved names de-reserved), so no remote value can shape
    the path. The ``[__issueid__]`` handshake tag carries the issue id (or the
    queue id when the issue is unknown) for the import join.
    """
    series = safe_path_component(
        series_title or fallback_title, fallback="series"
    )
    issue = safe_path_component(issue_number, fallback="issue")
    tag = str(issue_id) if issue_id is not None else f"q{queue_id}"
    return f"{series} {issue} [__{tag}__]{ext}"


def resolve_output_path(staging_dir: Path, name: str) -> Path:
    """Resolve ``name`` inside ``staging_dir`` and confirm it cannot escape it
    (FRG-DDL-011 path-escape corpus). Raises :class:`DdlDownloadError` on any
    resolved path outside the staging directory."""
    staging = Path(staging_dir).resolve()
    candidate = (staging / name).resolve()
    if candidate != staging and staging not in candidate.parents:
        raise DdlDownloadError(
            f"generated name escaped the staging dir: {candidate}"
        )
    return candidate


def partial_path_for(staging_dir: Path, queue_id: int) -> Path:
    """The id-named partial file: ``<config>/ddl-staging/<id>.partial``."""
    return Path(staging_dir) / f"{queue_id}.partial"


@dataclass(frozen=True, slots=True)
class DownloadOutcome:
    """The result of one successful link download (before verification)."""

    partial_path: Path
    bytes_received: int
    final_url: str


def _content_range_offset(header: str | None) -> int | None:
    """The start offset from a ``Content-Range: bytes START-END/TOTAL`` header."""
    if not header:
        return None
    value = header.strip()
    low = value.lower()
    if low.startswith("bytes "):
        value = value[len("bytes "):]
    try:
        span = value.split("/", 1)[0]
        start = span.split("-", 1)[0].strip()
        return int(start)
    except (ValueError, IndexError):
        return None


async def download_link(
    *,
    factory: HttpClientFactory,
    url: str,
    partial_path: Path,
    allowlist: AllowList,
    search_expected: int | None = None,
    chunk_size: int = CHUNK_SIZE,
    _retried: bool = False,
) -> DownloadOutcome:
    """Stream ``url`` into ``partial_path`` with resume + size accounting.

    Raises :class:`DdlDownloadError` (host-failover-eligible) on any bad
    outcome: an off-allowlist hop, a missing Content-Length after retry, or a
    final size mismatch beyond tolerance.
    """
    partial_path = Path(partial_path)
    partial_path.parent.mkdir(parents=True, exist_ok=True)
    if not allowlist.allows(url):
        raise OutboundNotAllowedError(
            f"download URL is outside the provider allowlist: {urlsplit(url).hostname}"
        )

    existing = partial_path.stat().st_size if partial_path.exists() else 0
    headers: dict[str, str] = {}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"

    try:
        return await _stream_to_partial(
            factory=factory,
            url=url,
            partial_path=partial_path,
            allowlist=allowlist,
            existing=existing,
            headers=headers,
            search_expected=search_expected,
            chunk_size=chunk_size,
            retried=_retried,
        )
    except OutboundHttpError as exc:
        # An SSRF/egress refusal (e.g. a redirect hop to a private address) or a
        # transport fault is a host-specific failure — fail over, never crash.
        raise DdlDownloadError(
            f"download transport/egress refused: {exc}"
        ) from exc


async def _stream_to_partial(
    *,
    factory: HttpClientFactory,
    url: str,
    partial_path: Path,
    allowlist: AllowList,
    existing: int,
    headers: dict[str, str],
    search_expected: int | None,
    chunk_size: int,
    retried: bool,
) -> DownloadOutcome:
    client = factory.external()
    try:
        stream_cm = client.stream(
            "GET", url, headers=headers, hop_check=_hop_check(allowlist)
        )
        async with stream_cm as resp:
            outcome = await _consume_stream(
                resp,
                partial_path=partial_path,
                existing=existing,
                search_expected=search_expected,
                chunk_size=chunk_size,
            )
    finally:
        await client.aclose()

    content_length, _mode, start, _received, final_url = outcome
    if content_length is None and search_expected is None:
        if not retried:
            _truncate(partial_path)
            return await _stream_to_partial(
                factory=factory,
                url=url,
                partial_path=partial_path,
                allowlist=allowlist,
                existing=0,
                headers={},
                search_expected=search_expected,
                chunk_size=chunk_size,
                retried=True,
            )
        raise DdlDownloadError(
            "response lacked a usable Content-Length after retry (ad page?)"
        )

    final = partial_path.stat().st_size
    _check_final_size(final, content_length, start, search_expected)
    return DownloadOutcome(
        partial_path=partial_path, bytes_received=final, final_url=final_url
    )


async def _consume_stream(
    resp,
    *,
    partial_path: Path,
    existing: int,
    search_expected: int | None,
    chunk_size: int,
) -> tuple[int | None, str, int, int, str]:
    """Write the streamed body to ``partial_path`` with the resume decision +
    runaway cap; return (content_length, mode, start, received, final_url)."""
    content_length = _int_or_none(resp.headers.get("content-length"))
    # Decide append vs restart (FRG-DDL-009).
    if existing > 0:
        offset = _content_range_offset(resp.headers.get("content-range"))
        if resp.status_code == 206 and offset == existing:
            mode, start = "ab", existing
        elif resp.status_code in (200, 206):
            # 200 full body, or a 206 whose offset does not match: the server
            # did not honor our Range — restart from zero, NEVER append (the
            # resume-trust flaw, mylar-ddl §3.5).
            mode, start = "wb", 0
        else:
            # A non-2xx response on resume (403/416/500/…) is an ERROR page, not
            # file content — never stream its body into the partial. Fail fast so
            # the queue engine fails over to the next host (FRG-DDL-009).
            raise DdlDownloadError(
                f"unexpected HTTP {resp.status_code} on resume "
                "(Range not honored, error response); failing over"
            )
    else:
        if resp.status_code != 200:
            raise DdlDownloadError(
                f"unexpected HTTP {resp.status_code} for a fresh download"
            )
        mode, start = "wb", 0

    # Expected total bytes on disk when complete, if we can know it.
    expected_total: int | None = None
    if content_length is not None:
        expected_total = start + content_length
    cap = _runaway_cap(expected_total, search_expected, chunk_size)

    received = start
    with partial_path.open(mode) as handle:
        async for chunk in resp.aiter_bytes(chunk_size):
            handle.write(chunk)
            received += len(chunk)
            if cap is not None and received > cap:
                raise DdlDownloadError(
                    "download exceeded the expected size (runaway/ad page)"
                )
    return content_length, mode, start, received, resp.url


def _runaway_cap(
    expected_total: int | None, search_expected: int | None, chunk_size: int
) -> int | None:
    if expected_total is not None:
        return expected_total + chunk_size
    if search_expected is not None:
        return int(search_expected * (1 + SEARCH_SIZE_TOLERANCE)) + chunk_size
    return None


def _check_final_size(
    final: int, content_length: int | None, start: int, search_expected: int | None
) -> None:
    if content_length is not None:
        expected_total = start + content_length
        if final != expected_total:
            raise DdlDownloadError(
                f"size mismatch: got {final}B, Content-Length implied "
                f"{expected_total}B (truncated transfer)"
            )
        return
    if search_expected is not None:
        tolerance = search_expected * SEARCH_SIZE_TOLERANCE
        if abs(final - search_expected) > tolerance:
            raise DdlDownloadError(
                f"size mismatch: got {final}B vs ~{search_expected}B expected "
                "from the search result"
            )


def _int_or_none(value: str | None) -> int | None:
    if value is None or not str(value).strip().isdigit():
        return None
    return int(value)


def _truncate(path: Path) -> None:
    with path.open("wb"):
        pass


__all__ = [
    "CHUNK_SIZE",
    "KNOWN_DDL_HOSTS",
    "AllowList",
    "DownloadOutcome",
    "build_allowlist",
    "build_hop_check",
    "download_link",
    "partial_path_for",
    "resolve_output_path",
    "safe_output_name",
]
