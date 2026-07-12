# m5-credits-live-fetch

## Why

The v0.5.2 known issue: ComicVine's `issues/` **list** endpoint returns
`person_credits: null` regardless of `field_list` — credits exist only on
the per-issue **detail** endpoint (verified live 2026-07-11; the reason
Mylar's `singleIssue` fetches details). v0.5.0's zero-extra-requests ingest
premise was therefore false and production credit ingest is silently empty;
our fixtures masked it by serving credits on the list endpoint. The
Creators screens shipped honestly empty; this change makes them real.

## What Changes

- **Per-issue credit detail fetches (FRG-CRTR-001 amended)**: series
  refresh gains a bounded credit-fetch phase — after the issue walk, fetch
  `issue/4050-{id}/` (`field_list=id,person_credits`) for up to N issues
  per run (default 25, configurable) that still need credits, newest first
  (store/cover date), through the same rate-gated hardened client. The
  opportunistic list mapping stays (zero-cost if CV ever serves it).
- **Fetch bookkeeping (FRG-CRTR-002 amended, migration 0017)**:
  `issues.credits_fetched_at` marks completion so zero-credit issues are
  not refetched forever; a successful detail fetch stamps it; reconcile
  uses the same replace semantics. Repeated refreshes (scheduled staleness
  runs, `creators-backfill` force-runs) advance the tail until the library
  is covered.
- **Anti-masking fixtures**: mockhub/unit fixtures corrected so the LIST
  endpoint serves `person_credits: null` exactly like real CV, and the
  DETAIL endpoint serves the credits — a live-shape tripwire test pins the
  distinction so this class of masking cannot recur.
- **Deferred tour returns**: the `creators-grid` README shot + README
  Creators section (parked in v0.5.2) ship here, captured from real
  ingested credits.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `crtr`: FRG-CRTR-001 (detail-fetch ingest, bounded/newest-first) and
  FRG-CRTR-002 (fetch bookkeeping, migration 0017) amended.

## Non-goals

- No change to the creators API or screens (they already render whatever
  is stored).
- No parallel CV fetching — the single process-global rate gate stands.
- No credits re-fetch/refresh policy for issues already stamped (CV credit
  edits propagate only via a future explicit re-fetch mechanism; out of
  scope).
- No suggestions work (ch3 unchanged, follows this).

## Impact

- **Backend**: `metadata/comicvine.py` gains `get_issue_credits(issue_id)`;
  `library/flows/refresh.py` gains the bounded fetch phase (CV I/O outside
  the write lock, stamps + reconcile inside); migration 0017
  (`credits_fetched_at`); config `credits_fetch_per_refresh` (clamped).
- **Coordination**: migration 0017 claimed — the keystore branch (assumed
  0016→renumbered 0017) shifts to 0018; noted for the merge check.
- **Performance**: worst-case +N detail requests per refresh at the 2s
  gate ≈ +50s per run at the default bound; a 161-issue series covers in
  ~7 refresh runs (backfill force-runs accelerate on demand).
- **Security**: no new surface — same client, same egress profile, same
  sanitizer on the same untrusted field; RISK-011/039 unchanged.
- **Docs**: README tour + creators shot restored; CHANGELOG v0.5.3;
  manual already describes credits arriving via refreshes (now true).
- **SOUP**: none.

## Approval

Approved under the M4–M7 standing grant (M5 creators & follows) as the
defect-fix completing FRG-CRTR-001's already-approved intent; the
2026-07-11 known-issue record (v0.5.2 CHANGELOG + decisions context) is
the triggering evidence. Gate obligations unchanged.
