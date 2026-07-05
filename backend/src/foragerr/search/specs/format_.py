"""Format-profile specifications (FRG-SRCH-004).

- :class:`FormatAllowedSpec` — the container format must be permitted by the
  mapped series' format profile (FRG-QUAL-001). Unknown formats pass here:
  a release title rarely names its container, and the truth is re-checked at
  import time; rejecting all unknowns would reject nearly every comic.
- :class:`UpgradeAllowedSpec` — when the issue already has a file, the
  candidate must be a genuine upgrade (a strictly higher profile rung), and
  only when upgrades are enabled at all.

Revision/proper and per-format size bounds (FRG-QUAL-003/004) are M2 and absent
here, so the upgrade test is a pure rung comparison at M1.
"""

from __future__ import annotations

from ..context import FormatProfile
from ..decision import Rejection, RejectionType
from .base import Evaluation, EvaluationContext


class FormatAllowedSpec:
    name = "format-allowed"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        series = ev.mapping.series
        if series is None:
            return None
        if series.profile.allows(ev.fmt):
            return None
        return Rejection(
            reason=(
                f"Format not allowed: '{ev.fmt}' is not in the "
                "series' format profile"
            ),
            type=RejectionType.PERMANENT,
            spec=self.name,
        )


class UpgradeAllowedSpec:
    name = "upgrade-allowed"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        series = ev.mapping.series
        issue = ev.mapping.issue
        if series is None or issue is None:
            return None
        if not issue.files:
            return None  # nothing on disk -> any allowed format is wanted
        if ev.fmt is None:
            # An unknown container format is unjudgeable before download —
            # exactly as FormatAllowedSpec permits it here (import re-verifies).
            # Rejecting it as "not an upgrade" would also render a bare 'None'
            # in the reason string. Pass and let import decide (FRG-SRCH-004).
            return None
        if not ctx.config.upgrades_allowed:
            return Rejection(
                reason="Upgrades are disabled: a file already exists for this issue",
                type=RejectionType.PERMANENT,
                spec=self.name,
            )
        profile: FormatProfile = series.profile
        best_existing = max(profile.rung(f.format) for f in issue.files)
        candidate_rung = profile.rung(ev.fmt)
        if candidate_rung > best_existing:
            return None  # strictly better -> a genuine upgrade
        existing_fmt = max(issue.files, key=lambda f: profile.rung(f.format)).format
        return Rejection(
            reason=(
                f"Not an upgrade: existing '{existing_fmt}' file is at least as "
                f"good as this '{ev.fmt}' release"
            ),
            type=RejectionType.PERMANENT,
            spec=self.name,
        )
