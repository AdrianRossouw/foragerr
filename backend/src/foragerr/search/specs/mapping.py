"""Library-mapping specifications (FRG-SRCH-003).

Two specs report the two distinct mapping failures with distinct, user-visible
reasons:

- :class:`SeriesMatchSpec` — the parsed release resolves to no tracked series.
- :class:`IssueMatchSpec`  — it resolves to a series, but no concrete issue.

Both accept (not-applicable) when a *prior* stage already failed, so a garbage
title yields only "unable to parse", not a cascade of mapping noise.
"""

from __future__ import annotations

from ..decision import Rejection, RejectionType
from .base import Evaluation, EvaluationContext


class SeriesMatchSpec:
    name = "series-match"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        if not ev.parsed.success:
            return None  # parse spec already reported it
        if ev.mapping.series is not None:
            return None
        name = ev.parsed.series_name or ev.candidate.title
        return Rejection(
            reason=f"Unknown series: no tracked series matches '{name}'",
            type=RejectionType.PERMANENT,
            spec=self.name,
        )


class IssueMatchSpec:
    name = "issue-match"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        if not ev.parsed.success or ev.mapping.series is None:
            return None  # unknown series is reported elsewhere
        if ev.mapping.issue is not None:
            return None
        shown = ev.parsed.issue.display if ev.parsed.issue is not None else "?"
        return Rejection(
            reason=f"Unknown issue: '{shown}' is not a tracked issue of this series",
            type=RejectionType.PERMANENT,
            spec=self.name,
        )
