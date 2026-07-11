# Design — calendar-discovery-default

## Context

Owner decision 2026-07-11 (decisions.md): the Calendar is a discovery
surface first — Mylar pull-list philosophy — so All releases is the
default scope, superseding the handoff's Following default (which had
quietly contradicted the owner's 2026-07-05 domain direction).

## Goals / Non-Goals

**Goal**: default scope flip only. **Non-goals**: persisted scope
preference; any other calendar behavior.

## Decisions

1. **One-line state default** (`'following'` → `'all'`) — scope remains
   per-visit component state; a persisted preference waits for demand.
2. **Publisher-scoped banner suffix stays a Following affordance** — the
   All-scope banner already reads as the full-week census.

## Risks / Trade-offs

- [Big all-releases weeks are busier by default] → the "N followed" day
  markers and one-click Following narrow it; the info banner explains the
  census.

## Migration Plan

None. Rollback = revert.

## Open Questions

_None._
