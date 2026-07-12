# cv-budget-caching

## Why

ComicVine enforces **200 requests per hour per resource path** per API key, on
top of the velocity detection our existing limiter already respects. The
process-global gate (`metadata/ratelimit.py`, FRG-META-003/FRG-NFR-004) models
velocity only: at the default 2 s spacing foragerr can emit ~1800 requests/hour
and exhaust one path's 200-request budget in about seven minutes while
reporting itself healthy. The owner's live usage data (2026-07-12) showed the
`/issue` detail path at 75 requests/hour under *light* use — the
m5-credits-live-fetch signature, since `person_credits` is only served on the
issue detail endpoint. The failure mode is real: one prolific followed creator
or a refresh-all sweep queues hundreds of same-path calls and earns a
temporary ComicVine block mid-job. M6's Humble matching adds more ComicVine
traffic on top, so this hardening lands before it. ComicVine's own guidance is
to cache responses; our repeat traffic (per-series refresh walks) has an
obvious cache key we don't use yet (`date_last_updated`).

A small confirmed bug rides along (owner triage 2026-07-12, "put the cover ws
push into the 0.6.x somewhere"): the cover-cache write transaction updates
`series.cover_cached_at` without queuing any event, so an open series-detail
page never learns the cover arrived until a manual reload — the frontend
already versions cover URLs by `cover_cached_at` and would repaint correctly
if told.

## What Changes

- **Per-path hourly budgets in the ComicVine client** (`FRG-META-016`, new):
  the client accounts requests per CV resource path over a rolling hour and,
  when a path's soft ceiling (default 150/hour, configurable) is exhausted,
  refuses further requests on that path with a typed budget error carrying the
  resume time, instead of letting them through to burn the server-side limit.
  Health reporting gains the per-path budget state — a deferral is never
  silent.
- **Defer-and-resume at the call sites**: budget exhaustion mid-job produces a
  clean partial result plus natural resumption, not a failure loop — the
  credit backfill stops early and unstamped issues are picked up by later
  runs (the existing `credits_fetched_at` mechanism); command-based fetches
  record a deferred/failed result and retry via their existing staleness
  paths; interactive lookups surface the typed error through the existing
  error-surfacing UI.
- **Unchanged-volume refresh short-circuit** (`FRG-META-017`, new): a series
  refresh first fetches the volume detail and, when ComicVine's
  `date_last_updated` matches the value stored by the last complete refresh
  (and that refresh is recent enough — default within 7 days), skips the
  issue pagination walk entirely. This is the response-caching measure CV
  recommends, applied where our traffic actually repeats; the periodic full
  walk remains the correctness backstop. Requires one new `series` column
  (migration number assigned at implementation). `FRG-META-010`
  (feed-based changed-since sync) stays in the backlog — this is the
  cheap per-series complement, not that feature.
- **Amendments**: `FRG-META-003` and `FRG-NFR-004` (rate limiting) gain the
  per-path hourly dimension alongside velocity; `FRG-META-013` (cover cache)
  gains an explicit scenario that recording a newly cached cover announces
  itself on the event stream (the ride-along fix).
- **Review of the `/issue` consumer**: the credit-fetch targeting keeps its
  bounded newest-first behavior and skip-already-stamped filter; it becomes
  budget-aware (stops cleanly on the typed budget error) — behavior verified
  by tests under FRG-META-016.

## Capabilities

### New Capabilities

_None — both new requirements live in existing capabilities._

### Modified Capabilities

- `meta`: new `FRG-META-016` (per-path hourly budget with defer-and-resume and
  health surfacing), new `FRG-META-017` (unchanged-volume refresh
  short-circuit), amended `FRG-META-003` (rate limiting gains the hourly
  budget dimension), amended `FRG-META-013` (cover-cache stamp update is
  announced on the event stream).
- `nfr`: amended `FRG-NFR-004` (ComicVine politeness budget covers per-path
  hourly accounting, not just spacing).

## Non-goals

- **No feed-based incremental sync** — `FRG-META-010` (changed-since feed,
  UTC/Pacific conversion, 1500-item batching) remains a backlog item; this
  change only short-circuits the per-series walk.
- **No generic HTTP response cache** — no TTL cache of raw CV payloads;
  the two measures here (skip-unchanged walk, already-shipped credit stamps)
  are the caching with actual traffic behind it.
- **No change to interactive search UX** beyond honest error surfacing when a
  budget is exhausted (the existing lookup-error surface carries the message).
- **No indexer/DDL rate-limit changes** — `indexers/ratelimit.py` is out of
  scope; ComicVine only.
- **No retroactive backfill job** for credits; existing bounded-per-refresh
  backfill continues.

## Impact

- **Code**: `metadata/ratelimit.py` (budget accounting + health snapshot),
  `metadata/comicvine.py` (path classification on `_request`, typed
  `ComicVineBudgetExhausted`), `library/flows/refresh.py` (short-circuit,
  budget-aware credit phase, cover-stamp event), config settings (ceiling,
  short-circuit staleness bound), API health surfacing, frontend health
  display (small), one Alembic migration (new `series` column storing the
  last-seen `date_last_updated`).
- **Specs**: delta files for `meta` and `nfr` as listed above.
- **Registry**: allocates `FRG-META-016`, `FRG-META-017` (M6, proposed).
- **Tests**: tagged tests for META-016 (budget accounting, deferral paths,
  health), META-017 (short-circuit hit/miss/staleness-forced walk), META-013
  (cover stamp write queues an event; WS push observed in the existing
  bridge tests' pattern).
- **Manual** (FRG-PROC-011): `docs/manual/user/metadata.md` (refresh
  behavior: budget deferral + skip-unchanged) and
  `docs/manual/admin/configuration.md` (new settings, health states).
- **Security** (FRG-PROC-006): no new attack surface — no new listener,
  parser of untrusted input beyond fields already consumed
  (`date_last_updated` is sanitized like every CV field), credential, or
  outbound destination. No SOUP changes.
- **Release**: rides v0.6.0 (first M6 change; the keystore's breaking release
  follows separately).

## Approval

Owner instruction at the M6 kickoff (Adrian, 2026-07-12, session message):
"(2) the small cv-budget-caching change from the CV rate finding — per-path
budgets, defer-and-resume, response caching — before or alongside keystore
implementation … keep going with all approved work." Scope above matches that
instruction and the 2026-07-12 finding it references; recorded here per
FRG-PROC-009 at proposal time. Any scope the owner did not name (the
unchanged-volume short-circuit as the concrete "response caching" measure,
and the cover-push ride-along he separately scheduled for a v0.6.x change)
is called out in this proposal for his review at the next breakpoint.
