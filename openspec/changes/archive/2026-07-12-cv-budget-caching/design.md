# cv-budget-caching — design

## Context

ComicVine limits API keys to 200 requests per hour **per resource path**
(`/volume`, `/issues`, `/issue`, `/people`, `/volumes`, `/search_api`, …) plus
separate velocity detection. Our limiter (`metadata/ratelimit.py`) is one
process-global velocity gate: min-interval spacing (default 2 s, floor 0.25 s)
plus 420/429/ban-page exponential back-off with a degraded flag surfaced
through `comicvine_health()`. There is no hourly accounting and no per-path
dimension, so foragerr can burn a single path's server-side budget in minutes
while healthy. All CV traffic already flows through one funnel —
`ComicVineClient._request(path, params)` → `_fetch` → `gate().acquire()` —
which makes the path dimension cheap to add: the `path` argument is already in
hand at the gate call.

Current `/issue`-path consumers: the refresh credit phase
(`refresh.py::_select_credit_fetch_targets`, bounded per run by
`credits_fetch_per_refresh`, resumable via `issues.credits_fetched_at`).
Repeat traffic with an unused cache key: every `refresh-series` does the
volume detail plus a full issue pagination walk even when nothing changed;
CV serves `date_last_updated` on the volume detail.

The ride-along: `refresh.py::_cache_cover_best_effort` commits
`series.cover_cached_at` in its own write session with no `queue_event`, so
the WS bridge never tells the client the cover arrived (the frontend versions
cover URLs by `cover_cached_at` and repaints on invalidation — the push is the
only missing piece).

## Goals / Non-Goals

**Goals:**

- Never exhaust a ComicVine per-path hourly budget from inside foragerr: a
  soft client-side ceiling defers work before the server blocks us.
- Deferral is visible (health) and resumable (jobs pick up where they left
  off) — never silent, never a retry storm.
- Cut repeat refresh traffic with the `date_last_updated` short-circuit.
- Cover pushes reach open clients without a reload.

**Non-Goals:**

- Feed-based changed-since sync (FRG-META-010 stays in B).
- A generic HTTP response cache; persisting raw CV payloads.
- Indexer/DDL limiter changes; multi-process coordination (single-operator
  deployment, one process).

## Decisions

1. **Path classification = first URL segment, normalized.** The budget key is
   the first path segment of the request path with any trailing id/suffix
   dropped (`"volume/4050-123/"` → `"volume"`, `"issues/"` → `"issues"`).
   That matches how CV buckets its server-side budget (per resource path) and
   needs no table to maintain. Classification lives in the client
   (`_fetch`), which passes the bucket to the gate.

2. **Budget accounting joins the existing global gate** rather than a second
   object: `_RateGate` gains a per-bucket deque of monotonic-clock request
   timestamps; `acquire(min_interval, bucket)` prunes entries older than 3600 s
   and, when the bucket has ≥ ceiling entries, raises
   `ComicVineBudgetExhausted(bucket, resume_at)` **without sleeping** —
   blocking a caller for up to an hour would silently pin the command-queue
   slot; a typed refusal lets each call site choose its own recovery. The
   timestamp is appended only when the request is actually admitted, and the
   deque is bounded by the ceiling so memory is O(paths × ceiling).
   Alternative considered: a separate `BudgetLedger` object — rejected, the
   gate is already the one process-global CV funnel and `reset_gate()` is the
   established test-isolation hook.

3. **Soft ceiling default 150/path/hour, configurable**
   (`comicvine_hourly_path_budget`, floor 10, ceiling clamp 200 with a warning
   — an operator may lower it, never exceed CV's documented limit). 150
   leaves ~25% headroom for the operator's other tools sharing the key and
   for clock skew between our rolling window and CV's.

4. **`ComicVineBudgetExhausted` is a `ComicVineError` subclass** carrying
   `bucket` and `resume_at` (monotonic-derived seconds-until, exposed as
   `retry_after_seconds`). It is **not** a rate-limit signal: it must NOT flip
   the degraded back-off state (we refused locally; CV saw nothing). Call-site
   behavior:
   - **Credit phase (refresh)**: catch it, stop fetching further targets this
     run, log once; unstamped issues resume on later refreshes via
     `credits_fetched_at` — the mechanism that already exists. The refresh
     itself still succeeds.
   - **Bibliography fetch**: the existing `ComicVineError` handling already
     fails the command and preserves the cache/stamp; the staleness-driven
     re-enqueue retries later. No new code path, only a test.
   - **Cover fetch**: already best-effort logged-and-swallowed. No new code
     path, only a test.
   - **Interactive lookups (search/suggest)**: the typed error flows through
     the existing lookup-error surfacing (FRG-SRCH/UI error path) with an
     honest "ComicVine hourly budget exhausted, retries after HH:MM" message.

5. **Health**: `comicvine_health()` grows
   `path_budgets: {bucket: {used, ceiling, resumes_in_seconds}}` for buckets
   ≥80% used or exhausted (an empty map in the common case keeps the payload
   small), and a top-level `budget_exhausted: bool`. The existing health
   endpoint/UI surface it like the degraded flag today.

6. **Short-circuit persists CV's volume stamp, compared verbatim.** New
   nullable `series.cv_date_last_updated` (string, stored as CV serves it —
   we never parse or do timezone math on it; equality is the only operation).
   Refresh order becomes: volume detail (1 request) → if the fetched
   `date_last_updated` equals the stored one AND the last refresh was
   complete (`page.complete` recorded — reuse `refreshed_at` + a
   `last_walk_complete` boolean… no: **reuse existing columns**: store the
   stamp only after a COMPLETE walk, clear it on partial, so a bare equality
   check implies completeness) AND `refreshed_at` is within
   `comicvine_refresh_max_skip_days` (default 7) → skip the issue walk,
   reconcile nothing, still run the credit phase against DB-known unstamped
   issues, still cache the cover (URL sidecar already dedups), still emit
   `SeriesRefreshed`. Otherwise: full walk as today, then store the stamp
   (complete) or NULL (partial). Storing NULL on partial walks keeps the
   invariant "stamp present ⇒ last walk was complete" in one column.
   Alternative considered: separate boolean column — more state to keep
   consistent for no reader.

7. **Credit targets on the short-circuit path come from the DB** (issue rows
   with `credits_fetched_at IS NULL`, same newest-first ordering by store/cover
   date) instead of the walk's records — same bound, same stamping. This keeps
   credit backfill progressing on unchanged series (the common case for a
   large library) instead of parking it behind volume edits.

8. **Cover push**: `_cache_cover_best_effort`'s write session queues
   `SeriesRefreshed(series_id, partial=False)` in the same transaction that
   sets `cover_cached_at`. Reusing the existing event (vs a new CoverCached
   event) means zero bridge/frontend changes — the client already refetches
   series detail on it and the cover URL version flips. The event fires only
   when a cover was actually (re)fetched — the unchanged-URL early return
   stays push-free, so steady-state refreshes don't double-invalidate.

9. **Migration** takes the next free Alembic number at implementation time
   (expected 0019; the keystore then takes the following slot — its proposal
   assigns the number at implementation for exactly this reason). Single
   nullable TEXT column, no backfill (NULL = "no complete walk recorded yet"
   → first refresh after upgrade does a full walk).

## Risks / Trade-offs

- [CV bumps `date_last_updated` semantics or misses issue-level edits] → the
  staleness bound forces a full walk at least every
  `comicvine_refresh_max_skip_days` (default 7), and any partial walk clears
  the stamp; full refresh remains the correctness backstop (same posture as
  FRG-META-010's notes).
- [Rolling-window drift vs CV's server-side window] → 25% headroom (150 vs
  200) absorbs boundary effects; the window is deliberately conservative
  (client counts admissions, prunes at exactly 3600 s).
- [A long-running process restart loses budget history] → accepted: worst
  case foragerr under-counts after a restart and the server-side 420/429
  back-off (existing behavior) is the second line of defense.
- [Budget refusal surfaces as failures in job history] → deferrals are logged
  and phrased as deferrals ("resumes after HH:MM"), and the credit phase
  treats it as a clean stop, not an error result.
- [Monotonic clock vs wall clock for `resume_at`] → `retry_after_seconds` is
  a duration, converted to wall-clock display only at the UI edge.

## Migration Plan

Forward-only Alembic migration adding `series.cv_date_last_updated TEXT NULL`
(startup-applied per FRG-DB rules; pre-migration backup per existing
machinery). Rollback = restore backup (project-standard posture, no downgrade
scripts). No config migration: new settings have safe defaults.

## Open Questions

_None blocking — call-site behaviors are enumerated in Decision 4; anything
discovered mid-implementation that changes a decision above re-opens this
document before code diverges from it._
