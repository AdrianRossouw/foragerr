# Delta: crtr — m5-credits-live-fetch

## MODIFIED Requirements

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
