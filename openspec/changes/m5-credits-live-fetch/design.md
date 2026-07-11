# Design — m5-credits-live-fetch

## Context

Live probe (2026-07-11, in-session): CV `issues/?filter=volume:9723&
field_list=id,issue_number,person_credits` returns `person_credits: null`
on every row; the detail endpoint serves them. v0.5.0 ingest therefore
never stored a credit in production; fixtures masked it. The reconcile
machinery (diff/prune/survivors) is correct and stays — only the *supply*
of credits changes.

## Goals / Non-Goals

**Goals**: real credits via bounded detail fetches; fetch bookkeeping;
fixtures that mirror the real API; the deferred tour shot.
**Non-goals**: API/screens changes; parallel CV traffic; stamped-issue
re-fetch policy.

## Decisions

1. **Fetch phase lives in `refresh_series`, CV I/O outside the write
   lock.** After the walk: query credit-needing issue ids (unstamped),
   order newest-first, take the bound, fetch details sequentially through
   the gate, then stamp + reconcile inside the existing write transaction.
   Newest-first because current books matter most on screens; the tail
   backfills across runs.
2. **`credits_fetched_at` on `issues` (migration 0017)** rather than a
   side table — it is an attribute of the issue's ingest state, queried in
   the hot path (`WHERE credits_fetched_at IS NULL`), and cascades
   trivially. Index on the nullable column partial-filtered where SQLite
   allows.
3. **Bound is config (`credits_fetch_per_refresh`, default 25, clamp
   ≥1/≤200)** — one knob, documented rendering; 25×2s ≈ 50s added to a
   refresh, tolerable for background runs and force-runs.
4. **Failure = skip + retry-later.** A failed detail fetch logs at
   warning, leaves the stamp unset, and never fails the refresh — the
   next run retries naturally. No per-issue backoff bookkeeping (the
   provider-level ladder already handles CV-wide outages).
5. **Fixtures mirror reality.** mockhub + unit fixtures: list rows carry
   `person_credits: null`; detail responses carry credits. A tripwire
   test asserts the list-mapping path yields empty credits for a
   list-shaped fixture AND that ingest end-to-end still lands credits via
   the detail path — the pair fails if either side regresses to the old
   masking shape.
6. **Zero-credit issues stamp too** — the whole point of the marker;
   otherwise golden-age libraries refetch forever.

## Risks / Trade-offs

- [Large libraries take many runs to cover] → force-run `creators-backfill`
  accelerates on demand; scheduled staleness refreshes advance steadily;
  documented in the manual's Creators paragraph (already worded "arrive
  with metadata refreshes").
- [Refresh duration grows] → bounded and configurable; the fetch phase
  runs after reconciliation-critical work.
- [CV credit edits after stamping never propagate] → accepted non-goal,
  recorded in spec Notes.

## Migration Plan

Migration 0017 adds the nullable column + index; forward-only. No data
backfill needed (NULL = needs fetch is exactly right for existing rows).

## Open Questions

_None blocking._
