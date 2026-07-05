"""Parse specification (FRG-SRCH-002).

Pins the SRCH-facing half of the parser contract: the engine obtains the
parsed structure from the one shared change-2 parser, and an unparseable title
becomes a *rejection* carrying the parser's machine-readable reason — never an
exception that escapes the engine. The parse itself is performed once in the
engine; this spec only reports on its result.
"""

from __future__ import annotations

from ..decision import Rejection, RejectionType
from .base import Evaluation, EvaluationContext


class ParseSpec:
    name = "parse"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        if ev.parsed.success:
            return None
        reason_code = (
            ev.parsed.failure_reason.value
            if ev.parsed.failure_reason is not None
            else "unknown"
        )
        return Rejection(
            reason=f"Unable to parse release title ({reason_code})",
            type=RejectionType.PERMANENT,
            spec=self.name,
        )
