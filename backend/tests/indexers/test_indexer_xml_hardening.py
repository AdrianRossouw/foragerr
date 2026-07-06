"""Hardened XML parsing of untrusted indexer responses (FRG-SEC-002)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from foragerr.indexers.errors import IndexerMalformedError
from foragerr.indexers.xml import parse_indexer_xml, parse_untrusted_xml
from indexers_support import (
    BILLION_LAUGHS,
    EXTERNAL_ENTITY,
    JUNK_BYTES,
    QUADRATIC_BLOWUP,
    newznab_feed,
    feed_item,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = Path(__file__).resolve().parents[2] / "src"
HARDENED = SRC_DIR / "foragerr" / "indexers" / "xml.py"


@pytest.mark.req("FRG-SEC-002")
def test_billion_laughs_rejected_without_expansion():
    with pytest.raises(IndexerMalformedError):
        parse_indexer_xml(BILLION_LAUGHS)


@pytest.mark.req("FRG-SEC-002")
def test_quadratic_blowup_rejected():
    with pytest.raises(IndexerMalformedError):
        parse_indexer_xml(QUADRATIC_BLOWUP)


@pytest.mark.req("FRG-SEC-002")
def test_external_entity_not_resolved(tmp_path):
    # A file the external entity would exfiltrate if resolution were enabled.
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-XXE-CANARY")
    payload = EXTERNAL_ENTITY.replace(
        b"file:///etc/passwd", f"file://{secret}".encode()
    )
    with pytest.raises(IndexerMalformedError):
        parse_indexer_xml(payload)


@pytest.mark.req("FRG-SEC-002")
def test_oversized_document_fails_as_typed_error():
    with pytest.raises(IndexerMalformedError):
        parse_indexer_xml(b"<rss>" + b"x" * 5000 + b"</rss>", max_bytes=1024)


@pytest.mark.req("FRG-SEC-002")
def test_junk_bytes_fail_as_typed_error():
    with pytest.raises(IndexerMalformedError):
        parse_indexer_xml(JUNK_BYTES)


@pytest.mark.req("FRG-SEC-002")
def test_valid_feed_parses_cleanly():
    root = parse_indexer_xml(newznab_feed(feed_item(guid="a", title="Saga 007")))
    assert root.tag.endswith("rss")


@pytest.mark.req("FRG-SEC-002")
def test_parse_untrusted_xml_is_the_generalized_hardened_site():
    """The neutral entry point parses a valid feed and rejects a hostile one with
    the same hardening — new callers (ComicInfo) route through it."""
    root = parse_untrusted_xml(newznab_feed(feed_item(guid="a", title="Saga 007")))
    assert root.tag.endswith("rss")
    with pytest.raises(IndexerMalformedError):
        parse_untrusted_xml(BILLION_LAUGHS)


@pytest.mark.req("FRG-SEC-002")
def test_parse_indexer_xml_is_a_thin_alias():
    """The indexer alias delegates to the generalized site (same hardening)."""
    with pytest.raises(IndexerMalformedError):
        parse_indexer_xml(QUADRATIC_BLOWUP)


@pytest.mark.req("FRG-SEC-002")
def test_no_unhardened_xml_parser_constructed_in_src():
    """Every untrusted-XML parse site routes through the hardened parser — no
    other module in backend/src constructs a stdlib/lxml XML parser."""
    forbidden = re.compile(
        r"minidom|xml\.sax|xml\.dom|\blxml\b|pyexpat|cElementTree"
        r"|ElementTree\.parse|ElementTree\.fromstring"
        r"|from\s+xml\.etree\.ElementTree\s+import[^\n]*\b(fromstring|parse|XMLParser|iterparse)\b"
    )
    offenders: list[str] = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        if path == HARDENED:
            continue  # the single sanctioned parse site
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if forbidden.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "unhardened XML parser construction outside indexers/xml.py "
        "(FRG-SEC-002):\n" + "\n".join(offenders)
    )
    # The hardened site itself uses defusedxml.
    assert "defusedxml" in HARDENED.read_text(encoding="utf-8")
