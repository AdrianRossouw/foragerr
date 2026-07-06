"""Ordered import decision specifications with visible reasons (FRG-PP-005).

Same shape as the search decision engine (design decision 3): one class per
rule, a stable ``name``, and a pure ``evaluate`` returning an
:class:`ImportRejection` (reject) or ``None`` (accept / not-applicable). The
engine runs **all** specs — never short-circuits — so a blocked file carries the
full reason list, each reason user-visible (FRG-PP-005 scenario 1). Derived
facts (resolved issue, archive report, existing file, free space) are computed
once by the pipeline into an :class:`ImportEvaluation` and read here, so no spec
re-does I/O.

A rejection is either ``BLOCKED`` (needs operator action; the item stays for
review, never lost, never auto-deleted — FRG-PP-005 scenario 2) or ``FAILED``
(a corrupt/invalid archive routes to failed-download handling → blocklist +
re-search, FRG-PP-006). The pipeline maps the two to the ``import_blocked`` /
``import_failed`` history events respectively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from foragerr.importer.evidence import Evidence
from foragerr.security.archives import ArchiveReport


class RejectionKind(Enum):
    """Whether a rejection parks for review or routes to failed-download handling."""

    BLOCKED = "blocked"
    FAILED = "failed"


#: Duplicate-constraint vocabulary (FRG-PP-014). ``larger-size`` (default): an
#: incoming same-rung file must be strictly larger than the existing file to
#: replace it. ``preferred-format``: the format-profile preference decides — and
#: since a same-rung tie means the preference is already satisfied, the existing
#: file is kept.
DUPLICATE_CONSTRAINT_LARGER_SIZE = "larger-size"
DUPLICATE_CONSTRAINT_PREFERRED_FORMAT = "preferred-format"


@dataclass(frozen=True, slots=True)
class ImportRejection:
    """One spec's user-visible reason for rejecting a candidate (FRG-PP-005)."""

    reason: str
    spec: str
    kind: RejectionKind = RejectionKind.BLOCKED


@dataclass(frozen=True, slots=True)
class ImportEvaluation:
    """Derived facts about one candidate, computed once, read by every spec.

    ``series_id`` / ``issue_id`` are the resolved library entities (``None`` when
    mapping failed). ``existing_format`` / ``new_format`` and ``format_ladder``
    drive the upgrade check; ``free_bytes`` / ``needed_bytes`` / ``margin_bytes``
    the free-space check; ``archive`` is the shared :class:`ArchiveReport`.
    """

    evidence: Evidence
    size: int
    series_id: int | None = None
    issue_id: int | None = None
    archive: ArchiveReport | None = None
    existing_file_path: str | None = None
    existing_format: str | None = None
    new_format: str | None = None
    format_ladder: tuple[str, ...] = ()
    free_bytes: int = 0
    needed_bytes: int = 0
    margin_bytes: int = 0
    already_imported: bool = False
    junk_size_floor: int = 0
    mapping_warning: str | None = None
    #: Embedded ComicInfo read summary (FRG-IMP-024) — reported by the manual
    #: import listing and used by the conflict spec. ``comicinfo_conflict`` is set
    #: when an embedded id was present but did NOT silently win (unverified /
    #: conflicting with the filename match) so it surfaces as a review item.
    comic_info_present: bool = False
    embedded_cv_issue_id: int | None = None
    embedded_verified: bool = False
    comicinfo_conflict: bool = False
    #: Same-rung duplicate arbitration inputs (FRG-PP-014): the existing file's
    #: recorded size, both sides' `(fN)` fixed-release marker revisions
    #: (``None`` = unfixed), and the configured constraint. Read only by
    #: :class:`DuplicateConstraintSpec`.
    existing_size: int | None = None
    existing_fix_revision: int | None = None
    new_fix_revision: int | None = None
    duplicate_constraint: str = DUPLICATE_CONSTRAINT_LARGER_SIZE


class ImportSpec:
    """One accept/reject rule (protocol; each subclass sets ``name``)."""

    name: str = "spec"

    def evaluate(self, ev: ImportEvaluation) -> ImportRejection | None:  # pragma: no cover
        raise NotImplementedError


class RemotePathMappedSpec(ImportSpec):
    name = "remote-path-mapped"

    def evaluate(self, ev: ImportEvaluation) -> ImportRejection | None:
        if ev.mapping_warning is None:
            return None
        return ImportRejection(
            reason=(
                "the download client's completed path is not reachable locally; "
                "add a remote-path mapping for this client to make it importable"
            ),
            spec=self.name,
        )


class MappedToIssueSpec(ImportSpec):
    name = "mapped-to-issue"

    def evaluate(self, ev: ImportEvaluation) -> ImportRejection | None:
        if ev.mapping_warning is not None:
            return None  # the mapping spec already owns this failure
        if ev.series_id is not None and ev.issue_id is not None:
            return None
        return ImportRejection(
            reason="could not match this file to a known series and issue",
            spec=self.name,
        )


class EmbeddedIdConflictSpec(ImportSpec):
    """Block when a present embedded ComicInfo id conflicts with the filename
    match (FRG-IMP-024). The unverified/conflicting id does NOT silently win —
    the candidate resolved by the heuristic but the disagreement surfaces here as
    a review item rather than a silent mis-file. A verified embedded id (which
    won the reconciliation) never sets this flag, so it does not trip."""

    name = "embedded-id-conflict"

    def evaluate(self, ev: ImportEvaluation) -> ImportRejection | None:
        if ev.mapping_warning is not None or not ev.comicinfo_conflict:
            return None
        return ImportRejection(
            reason=(
                "the embedded ComicInfo ComicVine id "
                f"({ev.embedded_cv_issue_id}) conflicts with the filename match; "
                "confirm the correct issue before importing"
            ),
            spec=self.name,
        )


class ArchiveValidSpec(ImportSpec):
    name = "archive-valid"

    def evaluate(self, ev: ImportEvaluation) -> ImportRejection | None:
        if ev.mapping_warning is not None or ev.archive is None:
            return None
        if ev.archive.ok:
            return None
        return ImportRejection(
            reason=ev.archive.reason or "archive failed validation",
            spec=self.name,
            kind=RejectionKind.FAILED,  # corrupt/password → failed pipeline
        )


class JunkFilterSpec(ImportSpec):
    name = "not-a-sample"

    def evaluate(self, ev: ImportEvaluation) -> ImportRejection | None:
        if ev.mapping_warning is not None:
            return None
        if ev.size >= ev.junk_size_floor:
            return None
        return ImportRejection(
            reason=(
                f"file is only {ev.size} bytes, below the "
                f"{ev.junk_size_floor}-byte floor — treated as a sample/junk file"
            ),
            spec=self.name,
        )


class FreeSpaceSpec(ImportSpec):
    name = "free-space"

    def evaluate(self, ev: ImportEvaluation) -> ImportRejection | None:
        if ev.mapping_warning is not None:
            return None
        if ev.free_bytes >= ev.needed_bytes + ev.margin_bytes:
            return None
        return ImportRejection(
            reason=(
                f"not enough free space: need {ev.needed_bytes} bytes + "
                f"{ev.margin_bytes} margin, have {ev.free_bytes}"
            ),
            spec=self.name,
        )


class AlreadyImportedSpec(ImportSpec):
    name = "not-already-imported"

    def evaluate(self, ev: ImportEvaluation) -> ImportRejection | None:
        if not ev.already_imported:
            return None
        return ImportRejection(
            reason="this download has already been imported for this issue",
            spec=self.name,
        )


class UpgradeAllowedSpec(ImportSpec):
    name = "upgrade-allowed"

    def evaluate(self, ev: ImportEvaluation) -> ImportRejection | None:
        if ev.mapping_warning is not None or ev.existing_file_path is None:
            return None  # no existing file → nothing to upgrade over
        if same_rung(ev):
            # A same-rung tie is DuplicateConstraintSpec's case alone
            # (FRG-PP-014): the two specs partition on same_rung(), keeping this
            # spec's > (accept) / < (reject) verdicts byte-identical to the
            # pre-PP-014 engine.
            return None
        new_rank = _rank(ev.new_format, ev.format_ladder)
        old_rank = _rank(ev.existing_format, ev.format_ladder)
        if new_rank > old_rank:
            return None  # genuine upgrade
        return ImportRejection(
            reason=(
                f"an existing file ({ev.existing_format or 'unknown'} format) is "
                f"already present and this {ev.new_format or 'unknown'} file is not "
                "an upgrade over it"
            ),
            spec=self.name,
        )


class DuplicateConstraintSpec(ImportSpec):
    """Arbitrates ONLY the same-rung duplicate (FRG-PP-014): an incoming file
    whose format ties the existing file on the profile ladder. Profile-order
    upgrades and downgrades remain :class:`UpgradeAllowedSpec`'s (unchanged)
    verdicts — the two specs partition on :func:`same_rung`, so exactly one of
    them ever speaks for a given existing-file case.

    Tie order: `(fN)` fixed-release markers first (a higher revision always
    wins; an unfixed file never beats a fixed one; equal markers fall through),
    then the configured constraint — ``larger-size`` (default: the incoming
    file must be strictly larger to replace) or ``preferred-format`` (the
    profile preference decides, and a same-rung tie means it is already
    satisfied, so the existing file is kept)."""

    name = "duplicate-constraint"

    def evaluate(self, ev: ImportEvaluation) -> ImportRejection | None:
        if ev.mapping_warning is not None or ev.existing_file_path is None:
            return None
        if not same_rung(ev):
            return None  # a profile-order upgrade/downgrade — never a tie
        new_fix = ev.new_fix_revision or 0
        old_fix = ev.existing_fix_revision or 0
        if new_fix > old_fix:
            return None  # a newer fixed release always wins the tie
        if new_fix < old_fix:
            new_desc = f"(f{new_fix}) file" if new_fix else "unfixed file"
            return ImportRejection(
                reason=(
                    f"the existing file is a newer fixed release (f{old_fix}) "
                    f"than this {new_desc} — fixed releases always win the "
                    "duplicate tie"
                ),
                spec=self.name,
            )
        if ev.duplicate_constraint == DUPLICATE_CONSTRAINT_PREFERRED_FORMAT:
            return ImportRejection(
                reason=(
                    f"an existing file ({ev.existing_format or 'unknown'} format) "
                    "already satisfies the format preference at the same rung — "
                    "duplicate constraint 'preferred-format' keeps the existing "
                    "file"
                ),
                spec=self.name,
            )
        # larger-size (default): the incoming file must be strictly larger. An
        # unknown existing size conservatively keeps the existing file.
        if ev.existing_size is not None and ev.size > ev.existing_size:
            return None
        existing_desc = (
            f"{ev.existing_size} bytes"
            if ev.existing_size is not None
            else "unknown size"
        )
        return ImportRejection(
            reason=(
                "an existing file of the same format rung is already present "
                f"and this file ({ev.size} bytes) is not larger than it "
                f"({existing_desc}) — duplicate constraint 'larger-size'"
            ),
            spec=self.name,
        )


def _rank(fmt: str | None, ladder: tuple[str, ...]) -> int:
    """Preference rank of ``fmt`` in ``ladder`` (least→most); ``-1`` if unknown."""
    if fmt is None:
        return -1
    try:
        return ladder.index(fmt.lower())
    except ValueError:
        return -1


def same_rung(ev: ImportEvaluation) -> bool:
    """True when an existing file ties the incoming one on the profile ladder —
    the (and only the) case :class:`DuplicateConstraintSpec` arbitrates
    (FRG-PP-014). Also used by the pipeline's execute to tell a duplicate
    resolution from a profile upgrade when disposing of the replaced file."""
    return ev.existing_file_path is not None and _rank(
        ev.new_format, ev.format_ladder
    ) == _rank(ev.existing_format, ev.format_ladder)


def duplicate_win_reason(ev: ImportEvaluation) -> str:
    """Why the incoming file won a same-rung duplicate tie (FRG-PP-014) — the
    acceptance-side counterpart of :class:`DuplicateConstraintSpec`'s rejection
    reasons, recorded on the replacement history event so the outcome and its
    reason are both visible."""
    new_fix = ev.new_fix_revision or 0
    old_fix = ev.existing_fix_revision or 0
    if new_fix > old_fix:
        old_desc = f"f{old_fix}" if old_fix else "the unfixed existing file"
        return (
            f"duplicate tie won by fixed-release marker: f{new_fix} beats "
            f"{old_desc}"
        )
    return (
        f"duplicate tie won under the 'larger-size' constraint: {ev.size} bytes "
        f"replaces {ev.existing_size} bytes"
    )


def default_specs() -> tuple[ImportSpec, ...]:
    """The import specification set, in evaluation order (all run)."""
    return (
        RemotePathMappedSpec(),
        MappedToIssueSpec(),
        EmbeddedIdConflictSpec(),
        ArchiveValidSpec(),
        JunkFilterSpec(),
        FreeSpaceSpec(),
        AlreadyImportedSpec(),
        UpgradeAllowedSpec(),
        DuplicateConstraintSpec(),
    )


@dataclass(frozen=True, slots=True)
class ImportDecision:
    """The verdict on one candidate, with every rejection reason (FRG-PP-005)."""

    rejections: tuple[ImportRejection, ...]
    series_id: int | None
    issue_id: int | None

    @property
    def approved(self) -> bool:
        return not self.rejections

    @property
    def failed(self) -> bool:
        """A corrupt/invalid archive → failed-download handling (FRG-PP-006)."""
        return any(r.kind is RejectionKind.FAILED for r in self.rejections)

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(r.reason for r in self.rejections)


def decide(
    ev: ImportEvaluation, specs: tuple[ImportSpec, ...] | None = None
) -> ImportDecision:
    """Run every spec over ``ev`` and collect the reasons (FRG-PP-005)."""
    rejections = [
        rej
        for spec in (specs if specs is not None else default_specs())
        if (rej := spec.evaluate(ev)) is not None
    ]
    return ImportDecision(
        rejections=tuple(rejections),
        series_id=ev.series_id,
        issue_id=ev.issue_id,
    )


__all__ = [
    "AlreadyImportedSpec",
    "ArchiveValidSpec",
    "DUPLICATE_CONSTRAINT_LARGER_SIZE",
    "DUPLICATE_CONSTRAINT_PREFERRED_FORMAT",
    "DuplicateConstraintSpec",
    "EmbeddedIdConflictSpec",
    "FreeSpaceSpec",
    "ImportDecision",
    "ImportEvaluation",
    "ImportRejection",
    "ImportSpec",
    "JunkFilterSpec",
    "MappedToIssueSpec",
    "RejectionKind",
    "RemotePathMappedSpec",
    "UpgradeAllowedSpec",
    "decide",
    "default_specs",
    "duplicate_win_reason",
    "same_rung",
]
