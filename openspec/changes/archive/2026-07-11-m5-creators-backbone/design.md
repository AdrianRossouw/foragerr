# Design — m5-creators-backbone

## Context

Nothing in the system knows who made a comic: `ISSUE_FIELDS` never requests
`person_credits`, `IssueRecord` has no credit field, and no creators/credits
tables exist. The CV `issues/` list endpoint (already used for the batched
per-volume walk in `refresh_series`) serves `person_credits` per row, so the
ingest cost is payload bytes, not requests. Refresh already has the right
seams: CV I/O outside the write lock (refresh.py:95-98), a per-issue
upsert loop inside one transaction (`_reconcile`, refresh.py:167-183), and
partial-fetch tolerance (`Page.complete`).

Two M6 branches are in flight in worktrees (keystore: assumes migration
0016 + FRG-AUTH-011..013; humble-source). This change claims 0016 and
FRG-CRTR-001..004/FRG-API-023 first; the keystore branch renumbers at
rebase (agreed convention — second merger checks both counters and
docs/process/decisions.md).

## Goals / Non-Goals

**Goals**: credits ingest at zero marginal CV requests; creators/credits
storage with refresh reconciliation; one-time backfill; follow flag with
threshold seeding; read API for the M5 screens.

**Non-goals**: any UI (change 2); external bibliography/suggestions
(change 3); character/team/arc credits; creator merging; notifications.

## Decisions

1. **Credits ride the batched walk — no per-issue fetches.** Add
   `person_credits` to `ISSUE_FIELDS` only. Alternative (Mylar-style
   per-issue `singleIssue` fetches) rejected: N extra rate-limited requests
   per refresh for data the list endpoint already serves.

2. **Role normalization is a fixed vocabulary + verbatim retention.** CV
   roles are free-ish text (comma-joined, e.g. "penciler, inker"). Split on
   commas, casefold, map known tokens to the 9-slot vocabulary, unknown →
   `other`, always keep the verbatim string. The UI chips (change 2) key off
   normalized; nothing is lost for later refinement.

3. **Schema: `creators` + `issue_credits`, no series-level rollup table.**
   Per-series role aggregates (grid counts, profile rows) are queries over
   `issue_credits JOIN issues` — correct by construction and cheap at this
   scale (single-operator SQLite). A denormalized rollup would add a second
   write path to keep consistent. Revisit only if profile queries measurably
   hurt. `follow_touched` (nullable timestamp) records user ownership of the
   flag so seeding can distinguish "never touched" from "unfollowed".

4. **Reconciliation replaces per-issue credit sets inside the existing
   transaction.** For each upserted issue, diff stored vs fetched credit
   rows (keyed by person id + normalized role) and apply the delta —
   idempotent, and a repeat refresh writes nothing. Creator rows upsert by
   CV person id (name updates follow CV). Prune step: delete only creators
   with zero credits AND `follow_touched IS NULL` AND `followed = false` — a
   user-touched row survives even creditless, because pruning it would erase
   the unfollow memory and a later re-ingest would re-seed the creator
   followed (exactly the overwrite FRG-CRTR-004 forbids). Seeding runs after
   the per-series reconcile: creators crossing the ≥2-distinct-series
   threshold with `follow_touched IS NULL` flip on.

5. **Backfill = fan-out over `refresh-series`, guarded by a persisted
   marker.** A `creators-backfill` command enqueues deduplicated
   `refresh-series` per series (same shape as pull's missing-issue
   trigger). The one-time trigger is a row in the existing app-state/marker
   storage (whatever `library/flows` uses for one-time flags; if none
   exists, a `schema_markers`-style single-row table rides migration 0016)
   checked at startup after migrations. Alternative (ingest-on-read)
   rejected: hides cost in request paths and violates the no-CV-in-API rule.

6. **API shapes mirror the house style.** Creators list = paging envelope +
   aggregate header fields (like the groups projection); follow toggle is a
   PUT sub-resource mirroring the issue monitored toggle. camelCase wire,
   Pydantic resources, no CV passthrough.

## Risks / Trade-offs

- [Payload growth on big volumes (600+ issues × dense credits)] → still one
  page walk under the 16 MB byte cap; measured in tests with a dense
  fixture; cap unchanged.
- [CV role-string drift (new role spellings)] → unknowns land in `other`
  with verbatim retained; vocabulary extension is a data-only change.
- [Backfill hammers CV on large libraries] → it's the normal refresh queue
  under the global rate gate; dedup prevents pile-up; force-run available if
  the operator wants it now.
- [Keystore branch collision on 0016/registry] → explicitly coordinated:
  this change merges with 0016 + CRTR/API rows; keystore renumbers at
  rebase (their stated plan); decisions.md untouched here to avoid the
  third collision surface.

## Migration Plan

One forward-only migration (0016): `creators`, `issue_credits` (+ indexes on
`issue_credits.creator_id` / `.issue_id`), and the one-time marker row if no
marker mechanism exists. No changes to existing tables. Rollback = restore
backup (house rule). Backfill self-triggers post-migration.

## Open Questions

_None blocking._
