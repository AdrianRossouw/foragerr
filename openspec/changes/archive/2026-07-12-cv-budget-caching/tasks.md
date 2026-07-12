# Tasks: cv-budget-caching

## 1. Registry + scaffolding

- [x] 1.1 Allocate `FRG-META-016`, `FRG-META-017` in
      `docs/traceability/requirements-registry.md` (status `proposed`, M6) —
      done at proposal commit.
- [x] 1.2 Alembic migration (next free number) adding
      `series.cv_date_last_updated TEXT NULL`; forward-only, no backfill.
      (0019_series_cv_date_last_updated; SeriesRow column added; migration test.)

## 2. Budget gate (FRG-META-016)

- [x] 2.1 `metadata/ratelimit.py`: per-bucket rolling-hour admission ledger on
      `_RateGate` (deque of monotonic stamps, pruned at 3600 s, appended on
      admission only); `acquire(min_interval, bucket, budget)` raises typed
      `ComicVineBudgetExhausted(bucket, retry_after_seconds)` when the bucket
      is at ceiling — no sleep, no degraded flip.
- [x] 2.2 `metadata/comicvine.py`: classify the bucket from the request path's
      first segment in `_fetch`; new `ComicVineBudgetExhausted` exported as a
      `ComicVineError` subclass. (Covers routed through the budgeted acquire too,
      under a dedicated "covers" bucket — no bypass.)
- [x] 2.3 Settings: `comicvine_hourly_path_budget` (default 150, floor 10,
      clamp ≤200 with warning, in `effective_budget`).
- [x] 2.4 Health: `comicvine_health()` gains `path_budgets` (≥80%-used buckets
      only: used/ceiling/resumes_in_seconds) + `budget_exhausted`; surfaced
      via the ComicVine component as a degraded state + warning. No frontend
      change needed — the existing generic degraded-component + warning
      rendering carries the budget message and payload shape is unchanged.
- [x] 2.5 Call-site behavior: refresh credit phase stops cleanly on the typed
      error (refresh still succeeds; deferral logged once); bibliography-fetch
      and cover paths need no code (existing `except ComicVineError` swallows
      the subclass); interactive search/suggest surface the message with resume
      time (budget carve-out added to `_paginate`/`suggest_series` so it
      propagates, plus a dedicated `_comicvine_error_to_api_error` branch).
- [x] 2.6 Tagged tests (`FRG-META-016`): per-path isolation, no-degraded-flip,
      credit-phase defer+resume across two runs, health payload shape
      (warning/exhausted/compact + rollover-to-compact), window rollover
      re-admission, ceiling clamping, single-gate admission (also tags
      `FRG-META-003`), plus interactive-lookup surfacing + health-component
      degraded surfacing.

## 3. Refresh short-circuit (FRG-META-017)

- [x] 3.1 `refresh.py`: fetch volume detail first; equality + staleness-bound
      check against `series.cv_date_last_updated`; skip issue walk on hit
      (no reconcile), full walk otherwise; store stamp only after a COMPLETE
      walk, clear it on partial. (Short-circuit does NOT bump `refreshed_at`, so
      the staleness bound keeps measuring age since the last real walk.)
- [x] 3.2 Short-circuit path still: credit backfill from DB-known unstamped
      issues (`_select_credit_targets_from_rows`, same bound/ordering), cover
      maintenance, `SeriesRefreshed` emission.
- [x] 3.3 Setting `comicvine_refresh_max_skip_days` (default 7, floor 1 via
      `max(1, ...)` at use).
- [x] 3.4 Tagged tests (`FRG-META-017`): hit skips the walk (request count
      asserted), miss/changed/stale forces the walk, partial clears the stamp,
      credit backfill progresses on short-circuited series.

## 4. Cover push ride-along (FRG-META-013)

- [x] 4.1 `_cache_cover_best_effort`: queue `SeriesRefreshed(series_id,
      partial=False)` in the same write transaction as the
      `cover_cached_at` stamp; unchanged-URL early return emits nothing.
- [x] 4.2 Tagged test (`FRG-META-013`): stamp write queues the event; reuse
      path does not.

## 5. Docs + merge gate

- [x] 5.1 Manual: `docs/manual/user/metadata.md` (deferral + skip-unchanged
      refresh behavior + cover repaint), `docs/manual/admin/configuration.md`
      (two new settings + ComicVine health states section).
- [x] 5.2 Registry rows → `implemented` with the merge; regenerate matrix
      (`tools/trace.py`). — orchestrator owns at merge.
- [x] 5.3 Merge-gate checklist (commit-standard): full suites, trace, soup
      (no SOUP delta expected), manual sync, tiered review (small fleet +
      Codex), `--no-ff` merge, tag v0.6.0 + release notes. — orchestrator owns.
