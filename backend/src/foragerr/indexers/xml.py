"""The single hardened XML parse site for untrusted indexer responses
(FRG-SEC-002).

Every byte of untrusted XML foragerr parses — Newznab/Torznab RSS and error XML,
and (from M2) embedded ComicInfo.xml read out of comic archives — flows through
:func:`parse_untrusted_xml`. It is the ONLY place in ``backend/src`` that
constructs an XML parser, and it is configured so that:

- **DTD/DOCTYPE processing is disabled** (``forbid_dtd=True``) — this alone
  rejects billion-laughs and quadratic-blowup entity bombs, which depend on
  internal ``<!ENTITY>`` definitions in a DTD;
- **entity expansion is forbidden** (``forbid_entities=True``);
- **external entity resolution is disabled** (``forbid_external=True``) — no
  ``file:///etc/passwd`` is read, no outbound URL is fetched;
- **the body is size-bounded** — parsing runs under a byte cap (the HTTP
  factory already caps the fetch; this guards direct callers too).

Any hostile or malformed document terminates as a typed
:class:`~foragerr.indexers.errors.IndexerMalformedError` — never a crash, hang,
resource-exhaustion, or partial result. A static guard test asserts no other
XML parser is constructed anywhere in ``backend/src``.

:func:`parse_untrusted_xml` is the neutral, content-agnostic entry point;
:func:`parse_indexer_xml` is kept as a thin alias so the indexer callers and
their tests are undisturbed. New untrusted-XML callers (e.g. the ComicInfo read
in :mod:`foragerr.metadata.comicinfo`) call :func:`parse_untrusted_xml` directly
so the DTD/entity/external hardening is inherited unchanged and this stays the
one sanctioned parser-construction site.

One carve-out (FRG-SEC-002, v0-6-3-fixes): :func:`parse_nzb_xml` tolerates the
DOCTYPE the NZB 1.1 spec *mandates* — with entity declarations, external
resolution, and unbounded size still forbidden — because ``forbid_dtd`` rejects
every spec-conformant NZB outright. It is for NZB payloads only and lives here
so this module remains the single parser-construction site.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

from defusedxml.ElementTree import ParseError, fromstring
from defusedxml.common import DefusedXmlException

from foragerr.indexers.errors import IndexerMalformedError

#: Default parse byte cap (25 MiB) — matches the HTTP factory ceiling so a
#: directly-parsed document is bounded the same way a fetched one is.
DEFAULT_MAX_BYTES = 26_214_400


def parse_untrusted_xml(
    data: bytes | str, *, max_bytes: int | None = DEFAULT_MAX_BYTES
) -> Element:
    """Parse untrusted XML with all entity/DTD/external vectors off.

    The single hardened parse site for every untrusted-XML caller (indexer RSS,
    embedded ComicInfo). Raises :class:`IndexerMalformedError` for an oversized
    body, non-XML junk, or any hostile entity/DTD/external payload — a typed
    failure, no partial result returned.
    """
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if max_bytes is not None and len(raw) > max_bytes:
        raise IndexerMalformedError(
            f"untrusted XML exceeded the {max_bytes}-byte parse cap "
            f"({len(raw)} bytes); refused"
        )
    try:
        return fromstring(
            raw,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except DefusedXmlException as exc:
        # billion-laughs, quadratic-blowup, external-entity, or a bare DOCTYPE.
        raise IndexerMalformedError(
            f"untrusted XML rejected by hardening: {type(exc).__name__}"
        ) from exc
    except ParseError as exc:
        raise IndexerMalformedError(f"untrusted XML is not well-formed: {exc}") from exc


def parse_indexer_xml(
    data: bytes | str, *, max_bytes: int | None = DEFAULT_MAX_BYTES
) -> Element:
    """Thin alias of :func:`parse_untrusted_xml` for the indexer call sites."""
    return parse_untrusted_xml(data, max_bytes=max_bytes)


def parse_nzb_xml(
    data: bytes | str, *, max_bytes: int | None = DEFAULT_MAX_BYTES
) -> Element:
    """Parse NZB bytes: the ONE format whose spec mandates a DOCTYPE.

    The NZB 1.1 specification requires
    ``<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN" ...>``, so
    ``forbid_dtd`` would reject every real indexer's NZB (live-SABnzbd finding,
    v0-6-3-fixes). This entry point tolerates that DOCTYPE as an *inert*
    declaration while keeping every attack-bearing property forbidden
    (FRG-SEC-002 carve-out): entity declarations raise ``EntitiesForbidden``
    even inside the allowed DOCTYPE (billion-laughs/quadratic blowup), external
    resolution stays disabled (XXE — the DOCTYPE's PUBLIC/SYSTEM identifier is
    never fetched; expat does not resolve external DTD subsets), and the byte
    cap is unchanged.

    NZB payloads ONLY. Every other untrusted-XML caller uses
    :func:`parse_untrusted_xml`, which keeps DOCTYPE processing fully disabled.
    """
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if max_bytes is not None and len(raw) > max_bytes:
        raise IndexerMalformedError(
            f"NZB exceeded the {max_bytes}-byte parse cap ({len(raw)} bytes); refused"
        )
    try:
        return fromstring(
            raw,
            forbid_dtd=False,  # the ONLY divergence — see docstring
            forbid_entities=True,
            forbid_external=True,
        )
    except DefusedXmlException as exc:
        raise IndexerMalformedError(
            f"NZB rejected by hardening: {type(exc).__name__}"
        ) from exc
    except ParseError as exc:
        raise IndexerMalformedError(f"NZB is not well-formed XML: {exc}") from exc
