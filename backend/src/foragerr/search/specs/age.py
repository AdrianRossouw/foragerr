"""Age-based specifications (FRG-SRCH-004, FRG-IDX-009).

- :class:`YearSanitySpec`  — reject a parsed publication year that is clearly
  impossible (a corrupt parse), Permanent.
- :class:`RetentionSpec`   — reject usenet candidates older than the configured
  retention window (FRG-IDX-009), Permanent.
- :class:`MinAgeSpec`      — reject candidates younger than the configured
  minimum release age, **Temporary** (they can pass on a later run).

Age is computed from ``pub_date`` against the injected ``ctx.now`` so results
are deterministic in tests; a candidate with no ``pub_date`` skips the age
checks rather than guessing.
"""

from __future__ import annotations

from datetime import datetime

from ..decision import Rejection, RejectionType
from .base import Evaluation, EvaluationContext

_MIN_PLAUSIBLE_YEAR = 1900


def _naive(value: datetime) -> datetime:
    """Drop tz so naive-UTC ``now`` and any aware pub_date subtract cleanly."""
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


class YearSanitySpec:
    name = "year-sanity"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        year = ev.parsed.year
        if year is None:
            return None
        if _MIN_PLAUSIBLE_YEAR <= year <= ctx.now.year + 2:
            return None
        return Rejection(
            reason=f"Implausible year {year} in release title",
            type=RejectionType.PERMANENT,
            spec=self.name,
        )


class RetentionSpec:
    name = "retention"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        retention = ctx.config.retention_days
        pub = ev.candidate.pub_date
        if retention is None or pub is None:
            return None
        age_days = (_naive(ctx.now) - _naive(pub)).total_seconds() / 86400
        if age_days <= retention:
            return None
        return Rejection(
            reason=(
                f"Exceeds retention: {int(age_days)} days old, "
                f"limit is {retention} days"
            ),
            type=RejectionType.PERMANENT,
            spec=self.name,
        )


class MinAgeSpec:
    name = "min-age"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        min_minutes = ctx.config.min_age_minutes
        pub = ev.candidate.pub_date
        if min_minutes <= 0 or pub is None:
            return None
        age_minutes = (_naive(ctx.now) - _naive(pub)).total_seconds() / 60
        if age_minutes >= min_minutes:
            return None
        return Rejection(
            reason=(
                f"Too new: {int(age_minutes)} min old, "
                f"minimum release age is {min_minutes} min"
            ),
            type=RejectionType.TEMPORARY,
            spec=self.name,
        )
