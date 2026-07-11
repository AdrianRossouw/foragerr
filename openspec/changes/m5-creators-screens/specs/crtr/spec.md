# Delta: crtr — m5-creators-screens

## MODIFIED Requirements

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
