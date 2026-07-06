"""Table-driven link enumeration, host/quality selection, and dispatch.

The direct fix for mylar-ddl's two link-layer defects (§3.3):

- the 150-line copy-pasted host-preference ``if`` ladder becomes a small
  ordering over typed tables (FRG-DDL-004);
- the ``'GC_Mirror'`` vs ``'GC-Mirror'`` dispatch typo — mirror links silently
  hit no handler — becomes impossible: every :class:`Host` has a row in
  :data:`DISPATCH`, asserted complete by a test (FRG-DDL-005).

Quality tiers feed nothing DDL-private: the search provider stamps the tier as a
``ReleaseCandidate`` attribute so the shared change-4 comparator can use it; the
*download-time* preference here only orders which host/quality link to try
first, never whether a release is acceptable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from foragerr.http import EXTERNAL  # noqa: F401 — anchors the egress-profile intent


class QualityTier(StrEnum):
    """Quality sections a GetComics post can offer (mylar-ddl §1.5)."""

    HD_UPSCALED = "hd-upscaled"
    HD_DIGITAL = "hd-digital"
    SD = "sd"
    NORMAL = "normal"


class Host(StrEnum):
    """The download hosts a post can offer (mylar-ddl §1.5)."""

    MAIN = "main"
    MIRROR = "mirror"
    MEGA = "mega"
    MEDIAFIRE = "mediafire"
    PIXELDRAIN = "pixeldrain"


class DownloadStrategy(StrEnum):
    """How a host's link is fetched.

    ``DIRECT`` — a GetComics-served HTTP link streamed by the built-in
    downloader (main server + mirror). ``UNSUPPORTED`` — a third-party file
    host (Mega/MediaFire/Pixeldrain) whose bespoke adapter is backlog B; its
    handler fails the attempt cleanly so per-host failover advances to the next
    host, never a crash or a silent no-op (the anti-pattern of Mylar's typo).
    """

    DIRECT = "direct"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class HostHandler:
    """The concrete dispatch entry for one host (FRG-DDL-005)."""

    host: Host
    #: Persisted link-type label recorded on the queue row + provenance. Uses a
    #: hyphen consistently (no ``GC_Mirror``/``GC-Mirror`` split can arise).
    link_type: str
    strategy: DownloadStrategy


#: THE dispatch table. Every :class:`Host` MUST have exactly one row; the
#: completeness test enumerates ``Host`` against this map so a missing or
#: misspelled entry fails CI (regression-proofing mylar-ddl §3.3).
DISPATCH: dict[Host, HostHandler] = {
    Host.MAIN: HostHandler(Host.MAIN, "GC-Main", DownloadStrategy.DIRECT),
    Host.MIRROR: HostHandler(Host.MIRROR, "GC-Mirror", DownloadStrategy.DIRECT),
    Host.MEGA: HostHandler(Host.MEGA, "GC-Mega", DownloadStrategy.UNSUPPORTED),
    Host.MEDIAFIRE: HostHandler(
        Host.MEDIAFIRE, "GC-Media", DownloadStrategy.UNSUPPORTED
    ),
    Host.PIXELDRAIN: HostHandler(
        Host.PIXELDRAIN, "GC-Pixel", DownloadStrategy.UNSUPPORTED
    ),
}


def dispatch_for(host: Host) -> HostHandler:
    """The concrete handler for ``host`` — never a miss (FRG-DDL-005)."""
    return DISPATCH[host]  # KeyError here is a programming error, not a runtime path


#: Known paywall / URL-shortener hosts rejected AT PARSE time, never fetched
#: (mylar-ddl §1.5 — ``sh.st`` and friends). Matched as a host suffix.
PAYWALL_HOSTS: frozenset[str] = frozenset(
    {"sh.st", "adf.ly", "ouo.io", "shorte.st", "linkvertise.com"}
)

#: Anchor-title fragments that are NOT downloads (skipped, not rejected).
NON_DOWNLOAD_LABELS: frozenset[str] = frozenset({"read online", "read"})

#: Map an anchor's title/label text onto a :class:`Host` (mylar-ddl §1.5).
_HOST_LABELS: tuple[tuple[str, Host], ...] = (
    ("mirror", Host.MIRROR),
    ("mega", Host.MEGA),
    ("mediafire", Host.MEDIAFIRE),
    ("media fire", Host.MEDIAFIRE),
    ("pixeldrain", Host.PIXELDRAIN),
    ("pixel drain", Host.PIXELDRAIN),
    ("download now", Host.MAIN),
    ("main server", Host.MAIN),
    ("main download", Host.MAIN),
)

#: Map a quality-section label onto a :class:`QualityTier`.
_QUALITY_LABELS: tuple[tuple[str, QualityTier], ...] = (
    ("hd-upscaled", QualityTier.HD_UPSCALED),
    ("upscaled", QualityTier.HD_UPSCALED),
    ("hd-digital", QualityTier.HD_DIGITAL),
    ("hd digital", QualityTier.HD_DIGITAL),
    ("sd-digital", QualityTier.SD),
    ("sd digital", QualityTier.SD),
    ("sd", QualityTier.SD),
)


def classify_host(label: str) -> Host | None:
    """Map anchor label → host, or ``None`` when it is not a download link."""
    text = (label or "").strip().lower()
    if not text:
        return None
    if any(fragment in text for fragment in NON_DOWNLOAD_LABELS):
        return None
    for fragment, host in _HOST_LABELS:
        if fragment in text:
            return host
    return None


def classify_quality(label: str | None) -> QualityTier:
    """Map a quality-section label → tier; unlabeled sections are ``NORMAL``."""
    text = (label or "").strip().lower()
    for fragment, tier in _QUALITY_LABELS:
        if fragment in text:
            return tier
    return QualityTier.NORMAL


def is_paywall_host(url_host: str) -> bool:
    """True when ``url_host`` is a known paywall/shortener (reject at parse)."""
    host = (url_host or "").strip().lower()
    return any(host == p or host.endswith("." + p) for p in PAYWALL_HOSTS)


@dataclass(frozen=True, slots=True)
class LinkCandidate:
    """One enumerated, selectable download link (FRG-DDL-004)."""

    host: Host
    quality: QualityTier
    link_type: str
    url: str
    strategy: DownloadStrategy


def _quality_rank(prefer_upscaled: bool) -> dict[QualityTier, int]:
    """Quality preference order (lower = preferred)."""
    if prefer_upscaled:
        order = (
            QualityTier.HD_UPSCALED,
            QualityTier.HD_DIGITAL,
            QualityTier.SD,
            QualityTier.NORMAL,
        )
    else:
        order = (
            QualityTier.HD_DIGITAL,
            QualityTier.SD,
            QualityTier.HD_UPSCALED,
            QualityTier.NORMAL,
        )
    return {tier: index for index, tier in enumerate(order)}


def parse_host_priority(raw: str) -> list[Host]:
    """Parse the comma-separated host-priority setting into typed hosts.

    Unknown tokens are ignored; any host missing from the configured order is
    appended in declared enum order so selection is never left without a total
    order over every offered host."""
    order: list[Host] = []
    for token in (raw or "").split(","):
        name = token.strip().lower()
        try:
            host = Host(name)
        except ValueError:
            continue
        if host not in order:
            order.append(host)
    for host in Host:
        if host not in order:
            order.append(host)
    return order


def order_candidates(
    candidates: list[LinkCandidate],
    *,
    host_priority: list[Host],
    prefer_upscaled: bool,
) -> list[LinkCandidate]:
    """Order enumerated links by configured host priority then quality
    preference (FRG-DDL-004). A stable total order so failover is deterministic."""
    host_rank = {host: index for index, host in enumerate(host_priority)}
    quality_rank = _quality_rank(prefer_upscaled)
    return sorted(
        candidates,
        key=lambda c: (
            host_rank.get(c.host, len(host_rank)),
            quality_rank.get(c.quality, len(quality_rank)),
        ),
    )


__all__ = [
    "DISPATCH",
    "NON_DOWNLOAD_LABELS",
    "PAYWALL_HOSTS",
    "DownloadStrategy",
    "Host",
    "HostHandler",
    "LinkCandidate",
    "QualityTier",
    "classify_host",
    "classify_quality",
    "dispatch_for",
    "is_paywall_host",
    "order_candidates",
    "parse_host_priority",
]
