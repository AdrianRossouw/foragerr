"""Decision outcomes for the unified decision engine (FRG-SRCH-001).

A :class:`Decision` is the engine's verdict on one :class:`ReleaseCandidate`.
Every specification that rejects contributes a :class:`Rejection` whose
``reason`` is a **user-visible** string rendered verbatim in interactive
search (FRG-UI-007) — write reasons for humans, not for logs.

The engine never short-circuits: *all* specifications run so the full reason
list is available (FRG-SRCH-001). The overall :class:`DecisionOutcome` is
derived from the collected rejections:

- no rejections            -> ``APPROVED``
- any Permanent rejection  -> ``REJECTED``
- otherwise (all Temporary)-> ``TEMPORARILY_REJECTED``
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from foragerr.parser.result import ParseResult
from foragerr.releases import ReleaseCandidate


class RejectionType(Enum):
    """Whether a rejection can clear on its own over time (FRG-SRCH-001)."""

    #: Will never pass without new information (wrong series, blocklisted).
    PERMANENT = "permanent"
    #: May pass on a later evaluation (too new, indexer backing off).
    TEMPORARY = "temporary"


class DecisionOutcome(Enum):
    """Overall verdict for a candidate (FRG-SRCH-001)."""

    APPROVED = "approved"
    TEMPORARILY_REJECTED = "temporarily-rejected"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Rejection:
    """One specification's reason for rejecting a candidate.

    ``reason`` is user-visible verbatim text; ``spec`` is the stable machine
    identifier of the specification (for tests, logs, and de-dup preference),
    never shown to users.
    """

    reason: str
    type: RejectionType
    spec: str


@dataclass(frozen=True, slots=True)
class Decision:
    """The engine's verdict on one candidate, with every rejection reason.

    ``parsed`` is always the :class:`ParseResult` obtained via the one shared
    parser (FRG-SRCH-002). ``mapped_series_id`` / ``mapped_issue_id`` are the
    library entities the candidate resolved to (FRG-SRCH-003), or ``None`` when
    mapping failed — carried here so the search-command layer can hand off a
    grab without re-deriving them.
    """

    candidate: ReleaseCandidate
    outcome: DecisionOutcome
    rejections: tuple[Rejection, ...]
    parsed: ParseResult
    mapped_series_id: int | None = None
    mapped_issue_id: int | None = None

    @property
    def approved(self) -> bool:
        return self.outcome is DecisionOutcome.APPROVED

    @property
    def reasons(self) -> tuple[str, ...]:
        """The user-visible reason strings, in specification order."""
        return tuple(r.reason for r in self.rejections)


def classify(rejections: tuple[Rejection, ...]) -> DecisionOutcome:
    """Derive the overall outcome from the collected rejections.

    A single Permanent rejection makes the whole decision ``REJECTED`` even
    when Temporary rejections are also present (FRG-SRCH-001).
    """
    if not rejections:
        return DecisionOutcome.APPROVED
    if any(r.type is RejectionType.PERMANENT for r in rejections):
        return DecisionOutcome.REJECTED
    return DecisionOutcome.TEMPORARILY_REJECTED
