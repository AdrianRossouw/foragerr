# m5-creators-backbone

## Why

M5 chapter 1. Creators are the comics-native answer to "what should I add
next" (Readarr-style, per the 2026-07-05 domain exploration): people follow
writers and artists across publishers, not just titles. Nothing in the system
knows who made a comic today — ComicVine's `person_credits` field is never
requested, mapped, or stored — so the M5 screens (grid, profile, follows,
suggestions) have no data to stand on. This change builds that backbone:
ingest, storage, read API, and the follow flag. No UI ships here; the
Creators nav entry waits for the screens change (shipped-screens rule,
FRG-UI-023).

## What Changes

- **Credits ingest (FRG-CRTR-001)**: `person_credits` joins `ISSUE_FIELDS` on
  the existing batched per-volume issue walk — no new CV requests, no new
  rate-limit pressure. Mapper and `IssueRecord` gain typed credit entries
  (CV person id, name, role string); names pass `sanitize_cv_text` like every
  other CV string (RISK-011 posture); role strings are normalized to a small
  vocabulary (writer, artist, penciler, inker, colorist, letterer, cover,
  editor, other) with the verbatim role retained.
- **Storage (FRG-CRTR-002, migration 0016)**: new `creators` table (CV person
  id unique, display name, followed flag + followed_at) and `issue_credits`
  association (issue FK CASCADE, creator FK, role). Refresh reconciliation
  replaces an issue's credits idempotently alongside the existing issue
  upsert loop; a partial CV fetch skips credit deletions exactly as it skips
  issue deletions (FRG-META-004/008 semantics). Orphaned creators (no
  credits, not followed) are pruned.
- **One-time backfill (FRG-CRTR-003)**: existing libraries get credits by a
  `creators-backfill` command that enqueues deduplicated `refresh-series`
  for every series (SCHED backbone, force-runnable, job-history-visible).
  Runs automatically once after the migration; safe to re-run.
- **Follow flag + seeding (FRG-CRTR-004)**: `followed` is a persisted,
  user-owned boolean with a toggle endpoint. On first ingest a creator
  crossing the threshold of **≥2 distinct library series** is seeded
  followed-on (the design's "Following defaults on for anyone with ≥2
  books"); seeding happens only when the user has never touched the flag
  (a user toggle is never overwritten by refresh).
- **Creators read API (FRG-API-023)**: `GET /api/v1/creators` (paged, each
  row carrying name, normalized roles, distinct-series count, followed flag,
  and up to N library work refs for the card spines) and
  `GET /api/v1/creators/{id}` (profile aggregates: per-series roles, library
  issue owned/total counts, publishers). `PUT /api/v1/creators/{id}/follow`
  toggles the flag. Read-only otherwise; no secrets exposed.

## Capabilities

### New Capabilities

- `crtr`: creators & follows domain — credits ingest (FRG-CRTR-001), storage
  + reconciliation (FRG-CRTR-002), backfill (FRG-CRTR-003), follow semantics
  (FRG-CRTR-004).

### Modified Capabilities

- `api`: new FRG-API-023 (creators resource + follow toggle).
- `meta`: FRG-META-006 amended (issue mapping now carries sanitized,
  role-normalized person credits when present; absent credits map to an
  empty list, never an error).

## Non-goals

- **No UI** — grid/profile/nav are m5-creators-screens (change 2); the
  series-detail credit surfacing also waits for change 2.
- **No "More from creator" bibliography** — the CV person→volumes fetch and
  add-suggestion affordances are change 3 (m5-creator-suggestions), where
  their security/egress posture is spec'd.
- **No notifications or auto-add** from follows — following is a flag with
  read-side value now; what it drives beyond the UI (suggestion surfacing)
  is change 3, and it never auto-adds (standing rule).
- **No character/team/arc credits** — person credits only.
- **No creator merging/aliasing** — CV person id is identity; a person with
  two CV records is two creators (revisit only if real data demands it).

## Impact

- **Backend**: `metadata/comicvine.py` (ISSUE_FIELDS), `metadata/mapping.py`
  + `models.py` (credit mapping), new `creators/` package (models, repo,
  reconciliation, commands), `library/flows/refresh.py` (credit persistence
  hook in `_reconcile`), `api/creators.py` router, migration
  `0016_creators_credits.py`.
- **Coordination**: migration 0016 and registry rows FRG-CRTR-001..004 +
  FRG-API-023 are claimed by this change; the in-flight keystore branch
  (assumes 0016, FRG-AUTH-011..013) renumbers at rebase per the agreed
  convention — whoever merges second checks both counters.
- **DB**: two new tables; issues cascade deletes their credits; no changes to
  existing tables.
- **Security**: no new attack surface — same CV endpoint, same hardened
  client, same sanitizer applied to the new strings; `person_credits` is
  additional untrusted content through the existing FRG-NFR-012 path.
  RISK-011 row gains a one-line ingest-arm note. No SOUP change.
- **Docs**: manual gets no user-visible section yet (no UI); roadmap M5
  section stays (screens/suggestions still unshipped). Registry + matrix
  updated.
- **Frontend**: none in this change.

## Approval

Approved under the M4–M7 standing grant (Adrian, 2026-07-10), which
enumerates "M5 creators & follows (new CRTR area)" for autonomous execution.
Per-change gate obligations unchanged (tiered review + Codex ninth angle
before merge).
