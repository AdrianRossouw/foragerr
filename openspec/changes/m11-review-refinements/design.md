# m11-review-refinements — design

## Context

Three dogfood refinements on shipped M11 surfaces. Current state (verified
against the code):

- **Group header** (`EntitlementGroupHeader.tsx`) renders select-all,
  counts, bundle name, collapse toggle — no search/match action. Per-row
  search (`EntitlementSearch`, FRG-UI-039) is mounted per row and takes a
  single `entitlementId`. `group_key` is computed on read
  (`stripped_key(query_term(human_name))`), not stored.
- **Sibling sweep** (`sources/review.py::_reresolve_sibling_proposals`)
  is invoked only from the add/degrade tail (`_resolve_as_match`), joins
  siblings by their own stored `cv_volume_id`, and writes proposals only.
  `match_entitlement` (plain match) invokes no sweep.
- **Grab** (`api/release.py::grab_release`) enqueues any cached
  `(indexer_id, guid)` with no approval check; the cache
  (`search_ops/cache.py`) stores a `GrabReleaseCommand` hand-off that
  does not carry the decision's approved verdict; the only gate is the
  frontend rendering Grab solely for `decision.approved`
  (`InteractiveSearchOverlay.tsx`).

## Goals / Non-Goals

**Goals**: resolve a group in one action; propagate a pick to siblings as
proposals (never commit); make the all-rejected case grabbable through a
deliberate, server-enforced, audited override.

**Non-goals**: see proposal (no auto-commit, no rule removal, no stored
`group_key` column, no decision-classification change).

## Decisions

**D1 — Grab gains a real server-side approval gate; force is the only
bypass.** Today the server enforces nothing. The cache table gains an
`approved` boolean (migration 0030) written per decision by
`cache_decisions`; `get_cached` returns it beside the hand-off.
`grab_release`: approved → grab (`triggered_by="interactive"`); not
approved + `force` → grab (`triggered_by="interactive-forced"`); not
approved + no force → typed 409. Rationale: surfacing a "Grab anyway"
button without this leaves the bypass client-only and the rejected-grab
hole open; gating on the server closes the hole AND makes force auditable.
Alternative — store nothing, treat any cache hit as grabbable, use `force`
only for the audit stamp — rejected: it leaves a rejected release grabbable
by anyone with the guid, which the review flagged as a latent gap.

**D2 — The sibling sweep becomes group-key-scoped and fires on every
operator pick.** A new sweep variant keys on `group_key` (computed in
Python, scoped to the acting `source_id` — the change-1 design's recorded
source-scoping follow-up) rather than the sibling's prior `cv_volume_id`,
and is called from both `match_entitlement` and the existing
`_resolve_as_match` tail. It reuses `_reresolve_sibling_proposals`'
proposal-only, exclude-non-`new` guard shape exactly. Rationale: matching
to an existing series is the case that swept nothing before, and
`group_key` (not prior proposal) is the grouping the operator actually
sees. Source-scoping bounds the per-pick scan (no cross-source rows, and
the group is small). Alternative — a stored/indexed `group_key` column for
a SQL pushdown — deferred: the Python scan over one source's `new` rows is
acceptable at the observed scale, and a column is a larger migration best
justified by a measured need.

**D3 — Group-header pick composes bulk-match with the D2 sweep.** An
in-library pick calls the existing bulk `match` action over the group's
member ids (from the client's `group.rows`). A not-in-library pick adds
the series once for the first member (existing single add), whose D2 sweep
re-proposes the rest, then the operator bulk-accepts. This reuses existing
endpoints; the only new backend surface is a thin bulk apply-to-group
convenience wrapping match + the sweep, so the header does one call.
Rationale: avoids a new bulk-add-with-cvid endpoint by leaning on the D2
sweep the change already builds.

## Risks / Trade-offs

- [Force-grab bypasses quality rules] → operator-authenticated, confirm-
  gated, audit-stamped (`interactive-forced`), reasons stay visible; the
  server gate means it is deliberate, not a client trick.
- [The new server gate could reject an approved grab on a schema/read
  bug] → the `approved` column defaults to the decision's real verdict at
  cache time; a migration-era NULL (pre-0030 cache rows) is treated as
  not-approved, which is fail-safe (refuse, offer force) rather than
  fail-open — tested.
- [Group sweep at 1318-row scale] → source-scoped Python scan over `new`
  rows only; excludes matched/ignored; proposal-only so no cascade of
  commits. Adversarial + scale angle at the gate.
- [Bulk apply-to-group partial failure] → each member resolves through the
  existing per-row path's guards; a failure on one member does not commit
  the others (reuses the bulk endpoint's per-id outcome shape).

## Migration Plan

Migration 0030: additive `approved` boolean on the interactive-search
cache table, defaulting fail-safe (absent ⇒ not approved). No data
rewrite; inert to older code. Rollback = revert the release tag.

## Open Questions

None blocking. Whether the group-header not-in-library path warrants a
single dedicated bulk-add endpoint (vs. add-first + sweep + accept) is an
implementation call within FRG-UI-043/FRG-SRC-014; the composed path ships
first and a dedicated endpoint is an easy follow-up if the round trips
bother the operator.
