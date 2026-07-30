# review-experience-2 — design

## Context

Facts established against the current tree:

- `source_entitlements` already stores `md5` (preferred copy) and the
  full per-format option list in `formats_json`; uniqueness is
  per-(source, gamekey, machine_name); there is no md5 index. md5 is
  used only for post-download integrity (grab verify → quarantine).
- Accepting one of an md5 pair today re-proposes the twin via the group
  sweep, and accepting the twin downloads a byte-identical file that the
  duplicate constraint then blocks (`import_blocked`) — the equal size
  is never "strictly larger".
- `review_status` ∈ (`new`, `matched`, `ignored`); ignore is the only
  parking state and it means an operator withdrawal — the v0.15.0
  `require_new` guards treat reversing it as forbidden, so dedupe must
  not reuse it.
- The picker (`EntitlementSearch`, shared by row and group header)
  already shows publisher/year/issue-count and already *normalizes*
  pasted CV URLs/ids — then submits them as a name filter, which finds
  nothing. `GET /series/lookup/volume/{id}` (FRG-API-026) exists with a
  frontend hook; only the Calendar add flow consumes it.
- The backend derives `trade_shape()` from the shared booktype
  vocabulary for its internal re-rank but ships no shape signal to the
  client. ComicVine has no booktype field (recorded in the
  m11-review-experience design).
- `group_key = stripped_key(query_term(name))` is shared by the read
  grouping AND the write-side sibling sweep (FRG-SRC-014); its module
  docstring forbids the two diverging. The containment primitive
  (`_contains_run`) already exists for the FRG-SRC-010 floor.
- Review rows are served `ORDER BY id` and rendered in arrival order;
  no within-group sort exists anywhere. The parser already extracts
  volume ordinals/issue numbers (the FRG-PP-022 machinery), but nothing
  exposes them on the entitlement resource.

## Goals / Non-Goals

**Goals**: one reviewable unit per byte-identical set; a picker that
discloses edition shape and honors its own advertised id paste; groups
that reunite a franchise split by naming and read in volume order.
**Non-goals**: cross-source dedupe, importer-side hashing, any change to
the write-side sweep key or the confidence floor, CV booktype.

## Decisions

**D1 — Duplicates are a review state, not a hidden flag.** New
`review_status` value `duplicate` plus a `duplicate_of` pointer to the
canonical row. Rationale: counts, filters, `require_new` guards and the
grab path all key on `review_status` — a parallel boolean would need a
guard added at every one of those seams individually, while a state
value inherits the existing exclusions (`_ACCEPTABLE_REVIEW_STATES`
stays `("new",)`, so a duplicate can never be matched/accepted/grabbed
without an explicit restore first). `ignored` is not reused because it
means operator withdrawal and carries reversal-refusal semantics.

**D2 — Linking is sync-time, same-source, stored-md5 equality, `new`
rows only.** Canonical = lowest id of the set; later same-md5 arrivals
park as `duplicate` at insert. Rows that are already `matched`/
`ignored`/`duplicate` are never re-linked or re-pointed — a decided row
is the operator's. If the *canonical* is later ignored or restored, the
copies stay parked (they point at a row, but their meaning is "this
exact file is represented once already"); restore of a copy is the
explicit way to review it independently. A one-time startup backfill
links pre-existing sets only when every member is still `new` (the rig
case), and is idempotent because linked copies are no longer `new`.
Null/absent md5 never links (no signal, no guess).

**D3 — The copies stay visible, recoverable, and honest.** The review
list's canonical row carries a copies chip (count + bundle names); a
Duplicates filter shows parked copies dimmed with Restore (mirroring the
Ignored presentation); pending counts exclude them. Restore returns a
copy to `new` with its pointer cleared and its proposal recomputed —
the same restore contract ignored rows have (FRG-SRC-004), extended to
the new state.

**D4 — Containment merge is read-side only; the sweep key does not
move.** The listing computes display groups by merging exact-fold groups
whose stripped keys contain one another as a contiguous token run — the
same rule the FRG-SRC-010 floor already trusts. The write-side sibling
sweep (FRG-SRC-014) keeps operating on the exact fold. Rationale: the
sweep rewrites proposals; widening its key widens a write blast radius
that was deliberately bounded at v0.15.0, and a wrong display merge
costs a glance while a wrong sweep rewrites rows. The shared-fold
"never diverge" docstring is amended to name the one sanctioned
difference: display grouping MAY merge containment-related keys, sweeps
MUST NOT. Group-header bulk actions stay safe under the merge because
they pass explicit member ids through the per-row `require_new`
contract.

**D5 — The sort key is server-computed, single-fold.** The entitlement
resource gains parsed `(volume_ordinal, issue_number)` derived by the
existing parser (the FRG-PP-022 derivation), and the client sorts group
members by it (nulls last, then name). A client-side regex would be a
second fold — exactly what the grouping module forbids.

**D6 — The picker cue is soft and honestly labeled; id paste resolves
by id.** Candidate resources gain a derived boolean (collected-edition
title cues, from the shared booktype vocabulary applied to the
candidate name) rendered as a badge — a hint, never a gate or a
re-rank change. A pasted CV volume URL/id routes to the existing
FRG-API-026 endpoint and renders the single resolved volume as a
pickable candidate (unknown id → the endpoint's honest 404-class note).
Both land in `EntitlementSearch`, so the group-header picker
(FRG-UI-043) inherits them without restatement.

## Risks / Trade-offs

- [Same md5 for genuinely distinct items] → md5 collision at store
  scale is not a practical concern for byte-identical dedupe (the store
  computed it from the file bytes); restore is the escape hatch either
  way.
- [Backfill skips sets with a decided member] → correct by principle
  (never re-link decided rows); the residue reviews as today. The rig's
  known pairs are all-`new`.
- [Containment merge over-merges two real distinct series sharing a
  token run] → display-only cost (rows sit under one header, every row
  keeps its own proposal/actions); no write surface moves.
- [New state value meets old clients] → additive enum; the UI ships in
  the same change; API consumers see `duplicate` only under the new
  filter or explicit id fetch.

## Migration Plan

Alembic 0032: add `source_entitlements.duplicate_of` (nullable int,
FK-less pointer like existing soft references if that is the local
pattern — follow it), index `(source_id, md5)`. Forward-only per
FRG-DB-002. Startup backfill (one-shot, idempotent by construction, D2)
links existing all-`new` md5 sets. Rollback = pre-migration backup, per
policy.

## Open Questions

None blocking. Bundle-name surfacing on the copies chip uses whatever
bundle identity FRG-SRC-011 already exposes on the row resource.
