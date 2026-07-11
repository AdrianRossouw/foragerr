"""Creators domain (FRG-CRTR-001..004).

Stores per-issue person credits and the creators they reference, reconciled
idempotently on series refresh, with a user-owned follow flag that is only ever
set by the explicit follow API (FRG-CRTR-004 — the system never derives a
follow). Credit *ingest* (CV mapping + role normalization) lives in
:mod:`foragerr.metadata.credits`; this package owns storage, reconciliation, and
the follow flag.
"""

from __future__ import annotations

from foragerr.creators.models import CreatorRow, IssueCreditRow
from foragerr.creators.reconcile import (
    prune_orphan_creators,
    reconcile_issue_credits,
    reconcile_series_credits,
)
from foragerr.creators.repo import (
    distinct_series_count,
    get_creator,
    get_creator_by_cv,
    list_issue_credits,
    set_creator_followed,
)

__all__ = [
    "CreatorRow",
    "IssueCreditRow",
    "distinct_series_count",
    "get_creator",
    "get_creator_by_cv",
    "list_issue_credits",
    "prune_orphan_creators",
    "reconcile_issue_credits",
    "reconcile_series_credits",
    "set_creator_followed",
]
