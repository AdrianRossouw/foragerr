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

The write half (FRG-PP-017, ComicInfo tagging on import) lives below this read
half: :func:`build_comicinfo_bytes` builds an element tree with the stdlib
``ElementTree`` *writer* (allowed — only parser construction is forbidden) from
the matched library records, and :func:`tag_cbz` streams a safe cbz rewrite. It
shares this module's :data:`COMICINFO_MAX_BYTES` cap and the ``ComicInfo.xml``
member conventions.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# The ElementTree *writer* (Element/SubElement/tostring) is allowed: the single
# hardened-parse guard (FRG-SEC-002) forbids only *parser* construction
# (``fromstring``/``parse``/``XMLParser``/``iterparse``). Building an output tree
# never parses untrusted input, so it stays clear of the guard.
from xml.etree.ElementTree import Element, SubElement, tostring

from foragerr.indexers.errors import IndexerMalformedError
from foragerr.indexers.xml import parse_untrusted_xml
from foragerr.security.archives import (
    DEFAULT_ARCHIVE_LIMITS,
    ArchiveReport,
    _unsafe_member_name,
)

if TYPE_CHECKING:
    # Type-only: importing the library models at runtime would pull in the
    # ``foragerr.library`` package __init__ (→ flows → importer), a cycle. The
    # write builder only reads attributes off the rows, so it duck-types them.
    from foragerr.library.models import IssueRow, SeriesRow

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


# --- write half (FRG-PP-017): build the tag + safe cbz rewrite ---------------

#: ComicVine issue page URL template — the ``4000-<id>`` carrier the read half
#: parses back out of ``<Web>``, so a foragerr-tagged file round-trips to the
#: same verified embedded id on re-import.
_CV_ISSUE_URL = "https://comicvine.gamespot.com/issue/4000-{cv_issue_id}/"


class ComicInfoTagError(Exception):
    """A ComicInfo rewrite could not be completed safely (FRG-PP-017).

    Raised by :func:`tag_cbz` after the partial temp zip has been unlinked and
    the placed file left byte-identical — a hostile/oversized member, or any IO
    failure mid-rewrite. The pipeline catches it, leaves the file untagged, and
    records a ``comicinfo_tag_failed`` warning event; the import is never failed.
    """


def _is_comicinfo_name(name: str) -> bool:
    """True for the single root-level ``ComicInfo.xml`` member (case-insensitive,
    no path separator) — the member the rewrite drops before appending a fresh
    one. Mirrors :func:`_select_member`'s selection rule."""
    if "/" in name or "\\" in name:
        return False
    return name.lower() == COMICINFO_MEMBER


def _text(parent: Element, tag: str, value: object | None) -> None:
    """Append ``<tag>value</tag>`` under ``parent`` only when ``value`` is set.

    Absent library fields are simply omitted (no empty elements), so the written
    ComicInfo carries only what the record actually knows."""
    if value is None:
        return
    text = str(value).strip()
    if not text:
        return
    child = SubElement(parent, tag)
    child.text = text


def build_comicinfo_bytes(series: SeriesRow, issue: IssueRow) -> bytes:
    """Build a ComicInfo.xml document from the matched library records (FRG-PP-017).

    Content comes ONLY from the resolved :class:`SeriesRow`/:class:`IssueRow` —
    never from any untrusted input — serialized with the stdlib ``ElementTree``
    *writer* (no parser is constructed). Only fields the record actually carries
    are emitted; ``Web`` embeds the ComicVine issue URL so a foragerr-tagged file
    re-imports to the same verified embedded id (FRG-IMP-024).
    """
    root = Element("ComicInfo")
    _text(root, "Series", series.title)
    _text(root, "Number", issue.issue_number)
    _text(root, "Title", issue.title)
    _text(root, "Volume", series.start_year)
    if issue.cover_date is not None:
        _text(root, "Year", issue.cover_date.year)
        _text(root, "Month", issue.cover_date.month)
        _text(root, "Day", issue.cover_date.day)
    _text(root, "Publisher", series.publisher)
    _text(root, "Web", _CV_ISSUE_URL.format(cv_issue_id=issue.cv_issue_id))
    return tostring(root, encoding="utf-8", xml_declaration=True)


def tag_cbz(
    path: str,
    xml_bytes: bytes,
    *,
    max_member_bytes: int = DEFAULT_ARCHIVE_LIMITS.max_member_bytes,
    max_comicinfo_bytes: int = COMICINFO_MAX_BYTES,
) -> None:
    """Rewrite the cbz at ``path`` with a fresh ``ComicInfo.xml`` (FRG-PP-017).

    Streams every source member into a temp zip created in the placed file's OWN
    directory (``mkstemp`` there → an atomic same-directory :func:`os.replace`),
    NEVER extracting to disk. For each source member the name is RE-CHECKED with
    :func:`~foragerr.security.archives._unsafe_member_name` (defense in depth even
    though ``inspect_archive`` already vetted it) and its declared size bounded by
    a per-member cap; any existing ``ComicInfo.xml`` is dropped and the freshly
    built one appended. The temp is fsync'd and atomically renamed over ``path``.

    ANY failure (a hostile/oversized member, an IO error mid-stream) unlinks the
    temp and leaves ``path`` byte-identical, raising :class:`ComicInfoTagError`.
    The caller (the pipeline) treats that as a non-fatal tagging failure.

    This is pure filesystem work (no DB, no parsing) so the pipeline runs it
    through its ``offload`` seam.
    """
    placed = Path(path)
    fd, tmp_name = tempfile.mkstemp(prefix=".foragerr-comicinfo-", dir=str(placed.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with (
            zipfile.ZipFile(placed) as src,
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst,
        ):
            for info in src.infolist():
                name = info.filename
                if _unsafe_member_name(name):
                    # A hostile name that slipped past inspection is refused here
                    # rather than copied to a traversed path (FRG-PP-017 scenario).
                    raise ComicInfoTagError(
                        f"refusing to copy unsafe member name: {name!r}"
                    )
                cap = max_comicinfo_bytes if _is_comicinfo_name(name) else max_member_bytes
                if info.file_size > cap:
                    # Bounded BEFORE any read — an oversized (existing ComicInfo or
                    # other) member degrades to a tagging warning, never an
                    # unbounded in-memory read (FRG-PP-017 scenario).
                    raise ComicInfoTagError(
                        f"member {name!r} declares {info.file_size} bytes over the "
                        f"{cap}-byte cap"
                    )
                if _is_comicinfo_name(name):
                    continue  # drop the stale ComicInfo; the fresh one is appended
                if info.is_dir():
                    dst.writestr(info, b"")
                    continue
                with src.open(info) as src_fp, dst.open(info, "w") as dst_fp:
                    shutil.copyfileobj(src_fp, dst_fp, length=1024 * 1024)
            dst.writestr("ComicInfo.xml", xml_bytes)
        # Flush the temp to disk before promoting it, mirroring fileops discipline.
        with open(tmp, "rb+") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, placed)  # atomic — a reader never sees a half-written cbz
    except BaseException as exc:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        if isinstance(exc, ComicInfoTagError):
            raise
        # Wrap any IO/zip failure so the pipeline handles one tagging-failure type.
        raise ComicInfoTagError(f"cbz rewrite failed for {path}: {exc}") from exc


__all__ = [
    "COMICINFO_MAX_BYTES",
    "COMICINFO_MEMBER",
    "ComicInfoTagError",
    "EmbeddedMetadata",
    "build_comicinfo_bytes",
    "read_embedded_metadata",
    "tag_cbz",
]
