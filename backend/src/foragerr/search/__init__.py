"""The comic decision engine: the single accept/reject/prioritize machinery
every candidate release passes through (FRG-SRCH-001..004, 006, 007, 010).

Public surface for the search-command / release-API area (change 4, area 3) and
for change 5's dynamic stores:

Engine
    - :class:`DecisionEngine` — ``evaluate(candidate, context) -> Decision`` and
      ``evaluate_all(candidates, context)``. Parses once, maps once, runs every
      specification, never raises.
    - :class:`Decision` / :class:`DecisionOutcome` / :class:`Rejection` /
      :class:`RejectionType` — the verdict types (reasons are user-visible).

Context the caller builds from the database
    - :class:`EvaluationContext` — library snapshot, optional search target,
      config, ``now``, and the three change-5 store seams.
    - :class:`LibrarySnapshot` / :class:`SeriesContext` / :class:`IssueContext`
      / :class:`ExistingFile` / :class:`FormatProfile` — the resolved library
      view.
    - :class:`SearchTarget` — the series+issue a search was issued for.
    - :class:`EngineConfig` — retention / min-age / term / upgrade knobs.

Change-5 store seams (inert defaults here; swap the injected object, not a spec)
    - :class:`QueueLookup` / :class:`BlocklistLookup` / :class:`FreeSpaceLookup`
      protocols and their inert stubs
      :class:`EmptyQueue` / :class:`EmptyBlocklist` / :class:`UnlimitedSpace`.

Prioritization & de-dup
    - :func:`order_decisions` / :func:`best_decision` / :func:`comparator_key`
      (FRG-SRCH-007).
    - :func:`deduplicate` (FRG-SRCH-010).
"""

from __future__ import annotations

from .comparator import best_decision, comparator_key, order_decisions
from .context import (
    DEFAULT_CONFIG,
    EmptyBlocklist,
    EmptyQueue,
    EngineConfig,
    EvaluationContext,
    ExistingFile,
    FormatProfile,
    FreeSpaceLookup,
    IssueContext,
    LibrarySnapshot,
    QueueLookup,
    BlocklistLookup,
    SearchTarget,
    SeriesContext,
    UnlimitedSpace,
)
from .decision import Decision, DecisionOutcome, Rejection, RejectionType, classify
from .dedup import deduplicate
from .engine import DecisionEngine
from .mapping import Mapping, map_release

__all__ = [
    # engine
    "DecisionEngine",
    "Decision",
    "DecisionOutcome",
    "Rejection",
    "RejectionType",
    "classify",
    # mapping
    "Mapping",
    "map_release",
    # context
    "EvaluationContext",
    "LibrarySnapshot",
    "SeriesContext",
    "IssueContext",
    "ExistingFile",
    "FormatProfile",
    "SearchTarget",
    "EngineConfig",
    "DEFAULT_CONFIG",
    # store seams
    "QueueLookup",
    "BlocklistLookup",
    "FreeSpaceLookup",
    "EmptyQueue",
    "EmptyBlocklist",
    "UnlimitedSpace",
    # prioritization / dedup
    "order_decisions",
    "best_decision",
    "comparator_key",
    "deduplicate",
]
