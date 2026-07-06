"""Import evidence aggregation (FRG-PP-003, FRG-PP-004).

For one candidate file, parse every available evidence layer — the grab record's
release title, the file name, the containing folder name, and the download-client
item title — through the **single** change-2 parser, then merge per field by a
fixed source-confidence order, recording which layer supplied each resolved
field (its provenance).

Source-confidence order (FRG-PP-004 scenario 1):

    grab record  >  ``[__issueid__]`` tag  >  file name  >  folder name  >  client title

The embedded ``[__issueid__]`` tag is a first-class high-confidence signal: if
any layer carries one it is captured on the :class:`Evidence` so the pipeline's
reconciliation can **short-circuit to a direct issue lookup** (the DDL handshake,
FRG-PP-003) ahead of any heuristic title/issue matching. Aggregation itself does
no I/O — it is a pure function of the candidate's strings, so it is fully
unit-testable and never depends on the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from foragerr.parser import ParseMode, ParseResult, parse
from foragerr.parser.result import Booktype, Issue, IssueRange

# Layer identifiers (also the provenance vocabulary for per-field sources).
LAYER_GRAB = "grab_record"
LAYER_FILENAME = "file_name"
LAYER_FOLDER = "folder_name"
LAYER_CLIENT = "client_title"
#: Provenance recorded for the issue id when it came from an embedded tag.
PROV_ISSUE_ID_TAG = "issue_id_tag"
#: Provenance recorded when the resolved (series, issue) came from a verified
#: embedded ComicInfo ComicVine id (FRG-IMP-024, design decision 3).
PROV_COMICINFO = "comicinfo"
#: Provenance recorded when the resolved (series, issue) came from a validated
#: manual override (FRG-PP-016, design decision 2) — human intent, top priority.
PROV_MANUAL_OVERRIDE = "manual_override"
#: Provenance key recorded when an embedded ComicInfo id was present but did NOT
#: silently win (unverified / conflicting with the filename match); its value is
#: the conflicting embedded ``cv_issue_id``. Surfaces the conflict as a
#: review/blocked item rather than a silent mis-file (FRG-IMP-024).
PROV_COMICINFO_CONFLICT = "comicinfo_conflict"

#: High → low confidence order for per-field selection (FRG-PP-004).
_LAYER_ORDER: tuple[str, ...] = (LAYER_GRAB, LAYER_FILENAME, LAYER_FOLDER, LAYER_CLIENT)


@dataclass(frozen=True, slots=True)
class Evidence:
    """Merged parse evidence with per-field provenance (FRG-PP-004)."""

    matching_key: str | None = None
    issue: Issue | None = None
    issue_range: IssueRange | None = None
    year: int | None = None
    volume_ordinal: int | None = None
    volume_year: int | None = None
    booktype: Booktype = Booktype.ISSUE
    release_group: str | None = None
    #: `(fN)` fixed-release marker revision (FRG-PP-014); ``None`` = unfixed.
    fix_revision: int | None = None
    issue_id: str | None = None
    #: field name → layer that supplied it (LAYER_* / PROV_ISSUE_ID_TAG).
    provenance: dict[str, str] = field(default_factory=dict)
    #: layer name → its full ParseResult, for the decision trace/diagnostics.
    layers: dict[str, ParseResult] = field(default_factory=dict)

    @property
    def issue_value(self) -> Fraction | None:
        return self.issue.value if self.issue is not None else None


def aggregate(
    *,
    grab_title: str | None = None,
    file_name: str | None = None,
    folder_name: str | None = None,
    client_title: str | None = None,
    reference_year: int,
) -> Evidence:
    """Aggregate evidence for one candidate (FRG-PP-004). Pure; never raises.

    Parses each provided layer via the single parser and merges per field in the
    fixed confidence order, recording provenance. The ``[__issueid__]`` tag is
    captured from the highest-confidence layer that carries one.
    """
    raw: list[tuple[str, str | None, ParseMode]] = [
        (LAYER_GRAB, grab_title, ParseMode.FILENAME),
        (LAYER_FILENAME, file_name, ParseMode.FILENAME),
        (LAYER_FOLDER, folder_name, ParseMode.FOLDER),
        (LAYER_CLIENT, client_title, ParseMode.FILENAME),
    ]
    layers: dict[str, ParseResult] = {
        name: parse(value, reference_year=reference_year, mode=mode)
        for name, value, mode in raw
        if value
    }

    provenance: dict[str, str] = {}

    def pick(field_name: str, getter):
        """First non-None field value in confidence order; records provenance."""
        for layer_name in _LAYER_ORDER:
            result = layers.get(layer_name)
            if result is None:
                continue
            value = getter(result)
            if value is not None and value != "":
                provenance[field_name] = layer_name
                return value
        return None

    matching_key = pick("series", lambda r: r.matching_key)
    issue = pick("issue", lambda r: r.issue)
    issue_range = pick("issue_range", lambda r: r.issue_range)
    year = pick("year", lambda r: r.year)
    volume_ordinal = pick("volume_ordinal", lambda r: r.volume_ordinal)
    volume_year = pick("volume_year", lambda r: r.volume_year)
    release_group = pick("release_group", lambda r: r.scan_group)
    fix_revision = pick("fix_revision", lambda r: r.fix_revision)

    booktype_val = pick("booktype", lambda r: r.booktype if r.booktype is not Booktype.ISSUE else None)
    booktype = booktype_val if booktype_val is not None else Booktype.ISSUE

    # Issue-id tag: highest-confidence layer carrying one wins; distinct
    # provenance so the pipeline can short-circuit to a direct lookup.
    issue_id: str | None = None
    for layer_name in _LAYER_ORDER:
        result = layers.get(layer_name)
        if result is not None and result.issue_id:
            issue_id = result.issue_id
            provenance["issue_id"] = PROV_ISSUE_ID_TAG
            break

    return Evidence(
        matching_key=matching_key,
        issue=issue,
        issue_range=issue_range,
        year=year,
        volume_ordinal=volume_ordinal,
        volume_year=volume_year,
        booktype=booktype,
        release_group=release_group,
        fix_revision=fix_revision,
        issue_id=issue_id,
        provenance=provenance,
        layers=layers,
    )


__all__ = [
    "LAYER_CLIENT",
    "LAYER_FILENAME",
    "LAYER_FOLDER",
    "LAYER_GRAB",
    "PROV_COMICINFO",
    "PROV_COMICINFO_CONFLICT",
    "PROV_ISSUE_ID_TAG",
    "PROV_MANUAL_OVERRIDE",
    "Evidence",
    "aggregate",
]
