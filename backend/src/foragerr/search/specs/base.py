"""Specification protocol and the per-candidate working object.

Every specification is one class with a stable ``name`` and a pure
``evaluate`` returning a :class:`~foragerr.search.decision.Rejection` (reject)
or ``None`` (accept). The engine runs *all* of them (FRG-SRCH-001), so a
specification whose precondition is unmet — e.g. a format check when the title
would not even parse — must ``return None`` (not-applicable) rather than pile
on a redundant rejection. Each spec therefore guards its own preconditions.

:class:`Evaluation` carries the once-computed derived facts (parse result,
library mapping, resolved container format) so specifications read them instead
of recomputing — parsing and mapping happen exactly once per candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from foragerr.parser.result import ParseResult
from foragerr.releases import ReleaseCandidate

from ..context import EvaluationContext
from ..decision import Rejection
from ..mapping import Mapping


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Derived facts about one candidate, computed once, read by every spec."""

    candidate: ReleaseCandidate
    parsed: ParseResult
    mapping: Mapping
    fmt: str | None

    @property
    def title(self) -> str:
        return self.candidate.title


class Specification(Protocol):
    """One accept/reject rule (FRG-SRCH-001)."""

    name: str

    def evaluate(
        self, ev: Evaluation, ctx: EvaluationContext
    ) -> Rejection | None: ...
