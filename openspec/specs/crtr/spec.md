# CRTR — Creators & Follows Specification

## Purpose

Requirements for the creators & follows domain (M5): per-issue creator
credits ingested from ComicVine, creator/credit storage with refresh
reconciliation, the one-time backfill, and user-owned follow semantics.
Allocated at m5-creators-backbone proposal time (FRG-PROC-002).
## Requirements

### Requirement: FRG-CRTR-001 — Per-issue creator credits ingest

The system SHALL ingest per-issue person credits from ComicVine via
**per-issue detail fetches**: ComicVine serves `person_credits` only on the
issue detail endpoint (verified live 2026-07-11 — the list endpoint returns
null for the field), so series refresh SHALL, after the issue walk, fetch
`issue/4050-{id}/` with a minimal `field_list` for up to a **configurable
bounded number** of issues per run (default 25, clamped ≥1) that still
need credits, **newest first** by store/cover date, through the existing
rate-gated hardened client — never in parallel past the process-global
gate. The batched list walk's mapping SHALL remain in place
opportunistically (rows carrying credits map at zero cost; absent credits
map to an empty list, never an error). Each credit SHALL be mapped exactly
as before: CV person id, display name through the shared CV sanitizer
(FRG-META-014), verbatim role plus the fixed normalized vocabulary
(`writer`, `artist`, `penciler`, `inker`, `colorist`, `letterer`, `cover`,
`editor`, `other`), capped per issue (RISK-011 bound). A failed detail
fetch SHALL leave the issue eligible for a later run without failing the
refresh.

- **Milestone**: M5
- **Source**: live CV probe 2026-07-11 (list endpoint returns
  person_credits null); mylar-comicvine.md §1.5 (singleIssue detail
  fetches); v0.5.2 known-issue record.
- **Notes**: Amends the v0.5.0 zero-extra-requests premise, which was
  false against the real API and masked by fixtures serving credits on the
  list endpoint. Fixtures now mirror the real shape (list = null credits,
  detail = credits) with a tripwire test. Worst case at defaults:
  +25 requests ≈ +50s per refresh under the 2s gate; repeated
  scheduled/backfill refreshes advance the tail across the library.

#### Scenario: Detail fetches are bounded, newest-first, rate-gated

- **WHEN** a series refresh runs against a volume with more
  credit-needing issues than the per-run bound
- **THEN** exactly the bound's worth of detail fetches are issued through
  the shared rate gate, targeting the newest credit-needing issues first,
  and the remaining issues are left for subsequent runs

#### Scenario: List rows genuinely lack credits; detail supplies them

- **WHEN** the issue walk returns rows with `person_credits: null` (the
  real list-endpoint shape) and the detail endpoint serves credits for a
  fetched issue
- **THEN** the walk maps empty credit lists without error, the detail
  fetch's credits are sanitized/normalized and reconciled onto the issue,
  and the fixture suite pins this list-null/detail-full shape

#### Scenario: A failed detail fetch degrades to retry-later

- **WHEN** one issue's detail fetch fails (transport, 5xx, malformed)
- **THEN** the refresh completes normally for everything else, the failed
  issue is not stamped and remains eligible next run, and the failure is
  logged — never raised

### Requirement: FRG-CRTR-002 — Creator and credit storage/reconciliation

The system SHALL store creators in a `creators` table (unique CV person id,
display name, `followed` flag with `followed_at`, `follow_touched` marker)
and per-issue credits in an `issue_credits` association (issue FK CASCADE →
creator FK, normalized role, verbatim role), created by a forward-only
migration per FRG-DB-002. Issues SHALL carry a nullable
`credits_fetched_at` timestamp (forward-only migration): a successful
detail fetch stamps it — including when the issue legitimately has zero
credits — so covered issues are never refetched; an unstamped issue is
credit-needing. Series refresh SHALL reconcile fetched credits idempotently
inside the existing per-issue write transaction: an issue's credit set is
replaced to match the fetched state (verbatim role re-authored in place on
change), a repeat refresh is a no-op, and a **partial** issue fetch
(FRG-META-004 `complete=False`) SHALL skip credit deletions exactly as it
skips issue deletions. Deleting an issue SHALL cascade its credits.
Reconciliation SHALL prune only creators with zero credits whose follow
flag was never user-touched and is off; a followed creator, or one the
user ever toggled, is never pruned.

- **Milestone**: M5
- **Source**: FRG-DB-002/007/008; FRG-META-004/008; m5-credits-live-fetch
  (fetch bookkeeping).
- **Notes**: Migration 0017 (`issues.credits_fetched_at`) claimed at
  proposal time — the in-flight keystore branch shifts to 0018.
  Re-fetching stamped issues (to pick up CV credit edits) is explicitly
  out of scope; a future mechanism may clear stamps.

#### Scenario: Refresh reconciles credits idempotently

- **WHEN** a series is refreshed twice with identical CV credit data
- **THEN** the second run changes no rows (same creators, same credit
  rows), and a run where CV dropped one credit removes exactly that
  association

#### Scenario: Zero-credit issues are stamped, not refetched forever

- **WHEN** a detail fetch returns an issue with no credits
- **THEN** the issue's `credits_fetched_at` is stamped with no credit rows
  written, and subsequent refreshes do not fetch that issue's detail again

#### Scenario: Partial fetch never deletes credits

- **WHEN** the issue walk returns `complete=False`
- **THEN** credit rows for issues absent from the partial page set are
  left intact, mirroring the existing absent-issue deletion skip

#### Scenario: Cascade and prune

- **WHEN** an issue is deleted, and separately a never-touched unfollowed
  creator loses their last credit
- **THEN** the issue's credit rows are cascade-deleted and the orphaned
  creator row is pruned

#### Scenario: Touched or followed creators survive creditless

- **WHEN** a creator the user unfollowed (or one currently followed) loses
  their last credit, and their series is later re-ingested
- **THEN** the creator row survives the creditless period with its
  `follow_touched` marker intact, so re-ingest does not re-seed the
  unfollowed creator to followed

### Requirement: FRG-CRTR-003 — One-time credits backfill

The system SHALL provide a `creators-backfill` command on the SCHED backbone
that enqueues a deduplicated `refresh-series` for every library series, so
existing libraries acquire credits without a bespoke ingest path. It SHALL
run automatically exactly once after the credits migration (guarded by a
persisted marker), SHALL be manually force-runnable via the standard task
surface (FRG-API-014), SHALL be safe to re-run (idempotent refreshes), and
SHALL record its run in job history like any other command.

- **Milestone**: M5
- **Source**: FRG-SCHED-003/007/008 (dedup, force-run, history);
  FRG-META-008 (refresh-series it delegates to).
- **Notes**: Deliberately just a fan-out over the existing refresh command —
  no second credits-ingest mechanism to maintain. Rate limiting is the
  normal CV gate; a large library backfills over time rather than fast.

#### Scenario: Backfill fans out deduplicated refreshes once

- **WHEN** the migration lands on a library with existing series and the app
  starts
- **THEN** `creators-backfill` runs once, enqueues one deduplicated
  `refresh-series` per series, records in job history, and does not run
  automatically again on subsequent restarts

#### Scenario: Manual force-run remains available

- **WHEN** the operator force-runs `creators-backfill` from the task surface
- **THEN** it executes again (idempotent), regardless of the one-time marker

### Requirement: FRG-CRTR-004 — Creator follow flag (explicit-only)

The system SHALL persist a user-owned `followed` flag per creator, togglable
via the API (FRG-API-023) and marked user-touched on every toggle. A follow
SHALL only ever result from an explicit user action: the system SHALL NOT
derive, seed, or default the flag from library contents or any other signal
(owner decision 2026-07-11, `docs/process/decisions.md` — supersedes the
v0.5.0 ≥2-distinct-series seeding and the design handoff §7 default). A
one-time data fix SHALL clear `followed` where `follow_touched IS NULL`
(exactly the seeded rows; explicit follows carry the touched marker and are
untouched). A user's follow or unfollow SHALL never be overwritten by
refresh or backfill. Following SHALL NOT trigger any automatic series add,
search, or download; its read-side effects (display, ch3 suggestion
surfacing) never acquire content by themselves.

- **Milestone**: M5
- **Source**: owner decision 2026-07-11 (v0.5.0 release-notes review);
  comics-domain exploration (subscribe → suggestions, never auto-add).
- **Notes**: The `follow_touched` marker (v0.5.0 schema) is what makes the
  unseed surgical — seeded follows are precisely the followed rows never
  touched by the user. The prune rule keeps its touched-survivor behavior;
  with seeding gone, a followed creator is always a touched creator after
  the data fix.

#### Scenario: No follow is ever derived

- **WHEN** ingest, refresh, or backfill processes a creator credited in any
  number of library series
- **THEN** the creator's `followed` flag is not set by the system — only
  `PUT /api/v1/creators/{id}/follow` changes it

#### Scenario: Seeded follows are unseeded once, explicit follows survive

- **WHEN** the data fix runs on a database containing v0.5.0-seeded follows
  (`followed = true`, `follow_touched IS NULL`) and explicit follows
  (`follow_touched` set)
- **THEN** seeded rows flip to unfollowed, explicit follows are untouched,
  and the fix does not run again on subsequent starts

#### Scenario: User toggles are never overwritten

- **WHEN** the user follows or unfollows a creator and any refresh or
  backfill runs afterwards
- **THEN** the flag remains exactly as the user set it

#### Scenario: Following causes no acquisition

- **WHEN** a creator is followed
- **THEN** no series is added, no search is enqueued, no download occurs,
  and no monitored flag changes anywhere
