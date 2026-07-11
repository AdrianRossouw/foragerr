# CRTR — Creators & Follows Specification

## Purpose

Requirements for the creators & follows domain (M5): per-issue creator
credits ingested from ComicVine, creator/credit storage with refresh
reconciliation, the one-time backfill, and user-owned follow semantics.
Allocated at m5-creators-backbone proposal time (FRG-PROC-002).
## Requirements

### Requirement: FRG-CRTR-001 — Per-issue creator credits ingest

The system SHALL ingest per-issue person credits from ComicVine by requesting
`person_credits` on the **existing batched per-volume issue walk**
(FRG-META-002's `issues/` list fetch) — issuing no additional ComicVine
requests and no per-issue detail fetches. Each credit SHALL be mapped to a
typed entry carrying the CV person id, the display name passed through the
shared CV sanitizer (`sanitize_cv_text`, FRG-META-014 — HTML/control/bidi
stripping and length cap), and the role: the verbatim role string retained
plus a normalized role from a fixed vocabulary (`writer`, `artist`,
`penciler`, `inker`, `colorist`, `letterer`, `cover`, `editor`, `other`;
unknown or compound roles split on commas and unmatched parts map to
`other`). An issue without credits SHALL map to an empty credit list — never
an error, never a skipped issue.

- **Milestone**: M5
- **Source**: mylar-comicvine.md §1.5 (singleIssue maps person credits);
  comics-domain exploration 2026-07-05 (creators as subscribable, Readarr
  model); design handoff §7/8 (role chips, roles line).
- **Notes**: `person_credits` on the list endpoint keeps ingest at zero
  marginal request cost — the payload grows within the existing byte cap.
  Credits are untrusted CV content and ride the FRG-NFR-012 path end to end.
  Character/team/arc credits are out of scope.

#### Scenario: Credits ride the existing issue fetch

- **WHEN** a series refresh walks a volume's issues and the response rows
  carry `person_credits`
- **THEN** each mapped issue record carries its typed credit entries
  (person id, sanitized name, verbatim + normalized role) and the walk
  issued exactly the same number of ComicVine requests as before the field
  was added

#### Scenario: Hostile credit strings are sanitized at ingest

- **WHEN** a credit's name or role contains HTML, control characters, or
  bidi-override/zero-width characters
- **THEN** the stored name/role are stripped clean by the shared sanitizer
  before persistence, and no raw string reaches the DB or API responses

#### Scenario: Absent credits are an empty list

- **WHEN** an issue row has no `person_credits` field, an empty list, or a
  malformed credits value
- **THEN** the issue maps normally with zero credit entries, the malformed
  value is dropped (logged at debug), and ingest of the remaining issues is
  unaffected

### Requirement: FRG-CRTR-002 — Creator and credit storage/reconciliation

The system SHALL store creators in a `creators` table (unique CV person id,
display name, `followed` flag with `followed_at`, `follow_touched` marker)
and per-issue credits in an `issue_credits` association (issue FK CASCADE →
creator FK, normalized role, verbatim role), created by a forward-only
migration per FRG-DB-002. Series refresh SHALL reconcile credits
idempotently inside the existing per-issue write transaction: an issue's
credit set is replaced to match the fetched state, a repeat refresh is a
no-op, and a **partial** issue fetch (FRG-META-004 `complete=False`) SHALL
skip credit deletions exactly as it skips issue deletions. Deleting an issue
SHALL cascade its credits. Reconciliation SHALL prune only creators with
zero credits whose follow flag was never user-touched and is off; a followed
creator, or one the user ever toggled, is never pruned — pruning a
user-unfollowed creator would erase the unfollow memory and allow a later
re-ingest to re-seed them followed, which FRG-CRTR-004 forbids.

- **Milestone**: M5
- **Source**: FRG-DB-002/007/008 (migration + transaction discipline);
  FRG-META-004/008 (partial-fetch tolerance this mirrors).
- **Notes**: Migration number is claimed as 0016 at proposal time
  (coordination note: the in-flight keystore branch renumbers at rebase).
  Creator display name updates on refresh (CV is authority for names, the
  user owns only `followed`).

#### Scenario: Refresh reconciles credits idempotently

- **WHEN** a series is refreshed twice with identical CV credit data
- **THEN** the second run changes no rows (same creators, same credit rows),
  and a run where CV dropped one credit removes exactly that association

#### Scenario: Partial fetch never deletes credits

- **WHEN** the issue walk returns `complete=False`
- **THEN** credit rows for issues absent from the partial page set are left
  intact, mirroring the existing absent-issue deletion skip

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
