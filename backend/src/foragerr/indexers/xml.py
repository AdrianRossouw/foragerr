"""The single hardened XML parse site for untrusted indexer responses
(FRG-SEC-002).

Every byte of Newznab/Torznab RSS and error XML foragerr parses flows through
:func:`parse_indexer_xml`. It is the ONLY place in ``backend/src`` that
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
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

from defusedxml.ElementTree import ParseError, fromstring
from defusedxml.common import DefusedXmlException

from foragerr.indexers.errors import IndexerMalformedError

#: Default parse byte cap (25 MiB) — matches the HTTP factory ceiling so a
#: directly-parsed document is bounded the same way a fetched one is.
DEFAULT_MAX_BYTES = 26_214_400


def parse_indexer_xml(
    data: bytes | str, *, max_bytes: int | None = DEFAULT_MAX_BYTES
) -> Element:
    """Parse untrusted indexer XML with all entity/DTD/external vectors off.

    Raises :class:`IndexerMalformedError` for an oversized body, non-XML junk,
    or any hostile entity/DTD/external payload — a typed failure, no partial
    result returned.
    """
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if max_bytes is not None and len(raw) > max_bytes:
        raise IndexerMalformedError(
            f"indexer XML exceeded the {max_bytes}-byte parse cap "
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
            f"indexer XML rejected by hardening: {type(exc).__name__}"
        ) from exc
    except ParseError as exc:
        raise IndexerMalformedError(f"indexer XML is not well-formed: {exc}") from exc
