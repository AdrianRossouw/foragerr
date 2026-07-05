"""Search-match specification (FRG-SRCH-006).

Under q=-only comic searching, wrong-series and wrong-issue hits are the norm,
so verifying that a candidate actually resolves to the series+issue that was
searched for is load-bearing, not defensive. This spec runs only when the
context carries a :class:`~foragerr.search.context.SearchTarget`; it compares
the *mapped* entities (from FRG-SRCH-003) against that target.

It is deliberately distinct from the mapping specs: mapping answers "which
tracked series/issue is this?"; search-match answers "is that the one we asked
for?". A release that maps cleanly to a *different* tracked series is a
"wrong series" here, not an "unknown series".
"""

from __future__ import annotations

from ..decision import Rejection, RejectionType
from .base import Evaluation, EvaluationContext


class SearchMatchSpec:
    name = "search-match"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        target = ctx.target
        if target is None:
            return None  # not a search path
        series = ev.mapping.series
        if series is None:
            return None  # unknown series already reported
        if series.series_id != target.series_id:
            name = ev.parsed.series_name or series.matching_key
            return Rejection(
                reason=(
                    f"Wrong series: release maps to '{name}', "
                    "not the series that was searched"
                ),
                type=RejectionType.PERMANENT,
                spec=self.name,
            )
        issue = ev.mapping.issue
        if issue is None:
            return None  # unknown issue already reported
        if issue.issue_id != target.issue_id:
            shown = ev.parsed.issue.display if ev.parsed.issue is not None else "?"
            return Rejection(
                reason=(
                    f"Wrong issue: release is issue '{shown}', "
                    "not the issue that was searched"
                ),
                type=RejectionType.PERMANENT,
                spec=self.name,
            )
        return None
