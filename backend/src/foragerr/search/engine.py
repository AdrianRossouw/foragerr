"""The unified decision engine (FRG-SRCH-001).

One engine, one ordered specification set, one verdict type. Every candidate
release — from automatic search, interactive search, or (later) RSS — passes
through here, so accept/reject behaviour is identical on every path.

Contract highlights:

- **Parse once, map once** (FRG-SRCH-002/003). The engine calls the single
  shared parser exactly once per candidate and resolves the library mapping
  once, then hands both to every specification via :class:`Evaluation`.
- **The engine never raises** (FRG-SRCH-002). The parser is total by contract,
  and specifications are pure; a hostile or garbage title becomes a rejection,
  not an exception. This is asserted by a fuzz sweep.
- **All specs run** (FRG-SRCH-001). No short-circuit — the full reason list is
  always available for interactive search display.
"""

from __future__ import annotations

from foragerr.parser import parse
from foragerr.releases import ReleaseCandidate

from .context import DEFAULT_CONFIG, EvaluationContext
from .decision import Decision, Rejection, classify
from .mapping import map_release
from .specs import Evaluation, Specification, default_specs
from .titles import candidate_format


class DecisionEngine:
    """Evaluates candidates against an ordered specification set."""

    def __init__(self, specs: tuple[Specification, ...] | None = None) -> None:
        self._specs: tuple[Specification, ...] = (
            specs if specs is not None else default_specs()
        )

    @property
    def specs(self) -> tuple[Specification, ...]:
        return self._specs

    def evaluate(
        self,
        candidate: ReleaseCandidate,
        context: EvaluationContext | None = None,
    ) -> Decision:
        """Return the :class:`Decision` for one candidate (never raises)."""
        ctx = context if context is not None else EvaluationContext(config=DEFAULT_CONFIG)

        parsed = parse(candidate.title, reference_year=ctx.reference_year)
        mapping = map_release(parsed, ctx)
        fmt = candidate_format(parsed, candidate.title)
        ev = Evaluation(candidate=candidate, parsed=parsed, mapping=mapping, fmt=fmt)

        rejections: list[Rejection] = []
        for spec in self._specs:
            rejection = spec.evaluate(ev, ctx)
            if rejection is not None:
                rejections.append(rejection)

        collected = tuple(rejections)
        return Decision(
            candidate=candidate,
            outcome=classify(collected),
            rejections=collected,
            parsed=parsed,
            mapped_series_id=(
                mapping.series.series_id if mapping.series is not None else None
            ),
            mapped_issue_id=(
                mapping.issue.issue_id if mapping.issue is not None else None
            ),
        )

    def evaluate_all(
        self,
        candidates: list[ReleaseCandidate],
        context: EvaluationContext | None = None,
    ) -> list[Decision]:
        """Evaluate many candidates against one shared context."""
        return [self.evaluate(c, context) for c in candidates]
