"""Term specifications (FRG-SRCH-004).

- :class:`MustNotContainSpec` — Mylar's IGNORE_SEARCH_WORDS: reject a release
  whose title contains any configured forbidden term.
- :class:`MustContainSpec`    — reject a release missing any configured
  required term.

Both match case-insensitively against the raw release title and are inert when
their term list is empty (the M1 default).
"""

from __future__ import annotations

from ..decision import Rejection, RejectionType
from .base import Evaluation, EvaluationContext


class MustNotContainSpec:
    name = "must-not-contain"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        title = ev.title.casefold()
        hit = next(
            (t for t in ctx.config.must_not_contain if t and t.casefold() in title),
            None,
        )
        if hit is None:
            return None
        return Rejection(
            reason=f"Contains ignored term '{hit}'",
            type=RejectionType.PERMANENT,
            spec=self.name,
        )


class MustContainSpec:
    name = "must-contain"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        title = ev.title.casefold()
        missing = next(
            (t for t in ctx.config.must_contain if t and t.casefold() not in title),
            None,
        )
        if missing is None:
            return None
        return Rejection(
            reason=f"Missing required term '{missing}'",
            type=RejectionType.PERMANENT,
            spec=self.name,
        )
