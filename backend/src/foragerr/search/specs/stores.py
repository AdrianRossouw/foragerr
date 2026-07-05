"""Dynamic-store specifications (FRG-SRCH-004).

These read the change-5 backing stores through the injected protocol seams.
Until change 5 wires real stores, the inert defaults
(:class:`~foragerr.search.context.EmptyQueue` etc.) make each spec accept every
candidate — yet the reject *paths* below are fully written and tested against a
populated fake, so change 5 turns them live by swapping the injected object,
never by editing a spec.

- :class:`AlreadyQueuedSpec` — the issue is already being downloaded.
- :class:`BlocklistSpec`     — the release was blocklisted, Permanent.
- :class:`FreeSpaceSpec`     — not enough disk space, Temporary.
"""

from __future__ import annotations

from ..decision import Rejection, RejectionType
from .base import Evaluation, EvaluationContext


class AlreadyQueuedSpec:
    name = "already-queued"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        series = ev.mapping.series
        issue = ev.mapping.issue
        if series is None or issue is None:
            return None
        if not ctx.queue.is_queued(series.series_id, issue.issue_id):
            return None
        return Rejection(
            reason="Already in the download queue for this issue",
            type=RejectionType.PERMANENT,
            spec=self.name,
        )


class BlocklistSpec:
    name = "blocklist"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        if not ctx.blocklist.is_blocklisted(ev.candidate):
            return None
        return Rejection(
            reason="Release is blocklisted",
            type=RejectionType.PERMANENT,
            spec=self.name,
        )


class FreeSpaceSpec:
    name = "free-space"

    def evaluate(self, ev: Evaluation, ctx: EvaluationContext) -> Rejection | None:
        series = ev.mapping.series
        size = ev.candidate.size_bytes
        if series is None or size is None:
            return None
        free = ctx.free_space.free_bytes(series.series_id)
        if free is None or free >= size:
            return None
        return Rejection(
            reason=(
                f"Insufficient free space: need {size} bytes, {free} available"
            ),
            type=RejectionType.TEMPORARY,
            spec=self.name,
        )
