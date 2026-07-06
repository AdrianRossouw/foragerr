"""Embedded ComicInfo.xml read (FRG-IMP-024).

The read half of the ComicInfo integration. During import the pipeline reads an
archive's embedded ``ComicInfo.xml`` (where present) so a *verified* embedded
ComicVine issue id can beat the filename-parse heuristic when matching a file to
a library issue (design decision 3).

Security posture (inherited, not re-implemented):

- **No parser is constructed here.** ComicInfo XML is untrusted, so parsing goes
  through the single hardened site :func:`foragerr.indexers.xml.parse_untrusted_xml`
  (FRG-SEC-002) — this module never touches ``xml.etree``/``defusedxml`` directly,
  and the static guard test forbids it to.
- **No extraction to disk.** Member selection uses the ``zipfile.ZipInfo`` list
  already vetted by :func:`foragerr.security.archives.inspect_archive`; the single
  root-level ``ComicInfo.xml`` is read into memory only, bounded by
  :data:`COMICINFO_MAX_BYTES`, respecting ``inspect_archive``'s never-extract
  contract.
- **Declared-size pre-check.** The member's *declared* ``file_size`` is checked
  against the small dedicated cap BEFORE any read, so an oversized member is
  skipped rather than loaded.
- **Parse-degraded, never fatal.** A malformed/hostile ComicInfo degrades to an
  :class:`EmbeddedMetadata` carrying a ``parse_error`` note; it never raises out
  of the read and the candidate continues on filename evidence.

The verified-vs-conflicting trust decision (does the embedded id resolve to a
library issue, is it in-scope, does it conflict with the filename match) is *not*
made here — it needs the database and lives in the reconciliation layer
(:func:`foragerr.importer.pipeline.reconcile`). This module only extracts the raw
embedded facts.

The write half (FRG-PP-017, ComicInfo tagging on import) is added alongside this
read half in a sibling change; it builds an element tree with the stdlib
``ElementTree`` *writer* (allowed — only parser construction is forbidden) from
matched library records and streams a safe cbz rewrite. It shares this module's
:data:`COMICINFO_MAX_BYTES` cap and the ``ComicInfo.xml`` member conventions.
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass

from foragerr.indexers.errors import IndexerMalformedError
from foragerr.indexers.xml import parse_untrusted_xml
from foragerr.security.archives import ArchiveReport

logger = logging.getLogger("foragerr.metadata.comicinfo")

#: The canonical embedded metadata member name (matched case-insensitively at the
#: archive root — no path separator).
COMICINFO_MEMBER = "comicinfo.xml"

#: Dedicated small per-member cap for the embedded ComicInfo member (1 MiB). Much
#: smaller than the general archive per-member cap — a metadata sidecar is tiny,
#: and this bounds both the declared-size pre-check and the in-memory read.
COMICINFO_MAX_BYTES = 1 * 1024 * 1024

#: ``<Web>`` values are ComicVine issue URLs whose path ends ``4000-<id>``.
_CV_WEB_RE = re.compile(r"\b4000-(\d+)\b")
#: ``<Notes>`` fallback: ComicTagger writes "[Issue ID <id>]".
_CV_NOTES_RE = re.compile(r"\bIssue ID\s+(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class EmbeddedMetadata:
    """Raw facts read from an archive's embedded ``ComicInfo.xml`` (FRG-IMP-024).

    ``comic_info_present`` is ``True`` whenever a root-level ``ComicInfo.xml``
    member existed (even if it was oversized or unparseable), so a caller can
    distinguish "no ComicInfo" from "ComicInfo present but unusable".
    ``cv_issue_id`` is the embedded ComicVine issue id (``cv_issue_id`` namespace,
    distinct from the internal ``[__issueid__]`` tag) or ``None``. ``parse_error``
    records the degraded reason when the member was present but could not be
    parsed (malformed/hostile/oversized); the other fields are then empty/partial.
    """

    comic_info_present: bool = False
    cv_issue_id: int | None = None
    series: str | None = None
    number: str | None = None
    title: str | None = None
    parse_error: str | None = None


def _select_member(infos: list[zipfile.ZipInfo]) -> zipfile.ZipInfo | None:
    """The single root-level ``ComicInfo.xml`` from a vetted ZipInfo list.

    Root-level only (no path separator) and matched case-insensitively; a member
    nested in a subdirectory is ignored (ComicInfo lives at the archive root).
    """
    for info in infos:
        name = info.filename
        if "/" in name or "\\" in name:
            continue
        if name.lower() == COMICINFO_MEMBER:
            return info
    return None


def _extract_cv_issue_id(root) -> int | None:
    """The embedded ComicVine issue id from ``<Web>`` (``4000-<id>``) or the
    ``<Notes>`` "[Issue ID <id>]" fallback; ``None`` when neither yields one."""
    web = (root.findtext("Web") or "").strip()
    match = _CV_WEB_RE.search(web)
    if match is not None:
        return int(match.group(1))
    notes = (root.findtext("Notes") or "").strip()
    match = _CV_NOTES_RE.search(notes)
    if match is not None:
        return int(match.group(1))
    return None


def read_embedded_metadata(
    path: str, report: ArchiveReport | None
) -> EmbeddedMetadata | None:
    """Read an archive's embedded ComicInfo.xml (FRG-IMP-024). Never raises.

    Returns ``None`` when there is no embedded metadata to read — an absent
    member, an oversized member (skipped under the cap), a magic-only/unlisted
    container (cbr/cb7 with no vetted member list), or a non-zip/failed archive.
    Returns an :class:`EmbeddedMetadata` (possibly ``parse_error``-degraded) when
    a root-level ``ComicInfo.xml`` was present.

    The declared member size is checked against :data:`COMICINFO_MAX_BYTES`
    BEFORE any read; the member is then read into memory only (never extracted)
    and parsed through the hardened untrusted-XML site.
    """
    if report is None or not report.ok or report.kind != "zip" or not report.listed:
        # Only a fully-listed zip has a vetted member list to select from; a
        # magic-only cbr/cb7 yields nothing (embedded read is best-effort there).
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            member = _select_member(archive.infolist())
            if member is None:
                return None
            if member.file_size > COMICINFO_MAX_BYTES:
                logger.info(
                    "comicinfo: ComicInfo.xml in %s declares %d bytes over the "
                    "%d cap; skipped",
                    path,
                    member.file_size,
                    COMICINFO_MAX_BYTES,
                )
                return None
            data = archive.read(member.filename)
    except (OSError, zipfile.BadZipFile) as exc:
        # The archive passed inspection but a concurrent change / IO error broke
        # the read: degrade to no embedded evidence, never fail the candidate.
        logger.warning("comicinfo: could not read ComicInfo.xml from %s: %s", path, exc)
        return None

    try:
        parsed = parse_untrusted_xml(data, max_bytes=COMICINFO_MAX_BYTES)
    except IndexerMalformedError as exc:
        logger.info("comicinfo: malformed/hostile ComicInfo.xml in %s: %s", path, exc)
        return EmbeddedMetadata(comic_info_present=True, parse_error=str(exc))

    try:
        cv_issue_id = _extract_cv_issue_id(parsed)
        series = (parsed.findtext("Series") or "").strip() or None
        number = (parsed.findtext("Number") or "").strip() or None
        title = (parsed.findtext("Title") or "").strip() or None
    except (ValueError, TypeError) as exc:  # a field present but unparseable
        return EmbeddedMetadata(comic_info_present=True, parse_error=str(exc))

    return EmbeddedMetadata(
        comic_info_present=True,
        cv_issue_id=cv_issue_id,
        series=series,
        number=number,
        title=title,
    )


__all__ = [
    "COMICINFO_MAX_BYTES",
    "COMICINFO_MEMBER",
    "EmbeddedMetadata",
    "read_embedded_metadata",
]
