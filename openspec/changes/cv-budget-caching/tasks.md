# Tasks: cv-budget-caching

## 1. Registry + scaffolding

- [ ] 1.1 Allocate `FRG-META-016`, `FRG-META-017` in
      `docs/traceability/requirements-registry.md` (status `proposed`, M6) —
      done at proposal commit.
- [ ] 1.2 Alembic migration (next free number) adding
      `series.cv_date_last_updated TEXT NULL`; forward-only, no backfill.

## 2. Budget gate (FRG-META-016)

- [ ] 2.1 `metadata/ratelimit.py`: per-bucket rolling-hour admission ledger on
      `_RateGate` (deque of monotonic stamps, pruned at 3600 s, appended on
      admission only); `acquire(min_interval, bucket, budget)` raises typed
      `ComicVineBudgetExhausted(bucket, retry_after_seconds)` when the bucket
      is at ceiling — no sleep, no degraded flip.
- [ ] 2.2 `metadata/comicvine.py`: classify the bucket from the request path's
      first segment in `_fetch`; new `ComicVineBudgetExhausted` exported as a
      `ComicVineError` subclass.
- [ ] 2.3 Settings: `comicvine_hourly_path_budget` (default 150, floor 10,
      clamp ≤200 with warning).
- [ ] 2.4 Health: `comicvine_health()` gains `path_budgets` (≥80%-used buckets
      only: used/ceiling/resumes_in_seconds) + `budget_exhausted`; surface
      through the existing health endpoint and frontend health display.
- [ ] 2.5 Call-site behavior: refresh credit phase stops cleanly on the typed
      error (refresh still succeeds; deferral logged once); verify
      bibliography-fetch and cover paths need no code (existing typed-error
      handling) with tests; interactive search/suggest surfaces the message
      with resume time via the existing lookup-error path.
- [ ] 2.6 Tagged tests (`FRG-META-016`): per-path isolation (one bucket
      exhausted, another proceeds), no-degraded-flip, credit-phase
      defer+resume across two runs, health payload shape (warning/exhausted/
      compact), window rollover re-admission, ceiling clamping, single-gate
      admission (budget consumed exactly once per wire request, covers
      included → also tags `FRG-META-003`).

## 3. Refresh short-circuit (FRG-META-017)

- [ ] 3.1 `refresh.py`: fetch volume detail first; equality + staleness-bound
      check against `series.cv_date_last_updated`; skip issue walk on hit
      (no reconcile), full walk otherwise; store stamp only after a COMPLETE
      walk, clear it on partial.
- [ ] 3.2 Short-circuit path still: credit backfill from DB-known unstamped
      issues (same bound/ordering, reuse `_select_credit_fetch_targets`
      shape), cover maintenance, `SeriesRefreshed` emission.
- [ ] 3.3 Setting `comicvine_refresh_max_skip_days` (default 7, floor 1).
- [ ] 3.4 Tagged tests (`FRG-META-017`): hit skips the walk (request count
      asserted), miss/absent/stale forces the walk, partial clears the stamp,
      credit backfill progresses on short-circuited series.

## 4. Cover push ride-along (FRG-META-013)

- [ ] 4.1 `_cache_cover_best_effort`: queue `SeriesRefreshed(series_id,
      partial=False)` in the same write transaction as the
      `cover_cached_at` stamp; unchanged-URL early return emits nothing.
- [ ] 4.2 Tagged test (`FRG-META-013`): stamp write queues the event; reuse
      path does not.

## 5. Docs + merge gate

- [ ] 5.1 Manual: `docs/manual/user/metadata.md` (deferral + skip-unchanged
      refresh behavior), `docs/manual/admin/configuration.md` (new settings,
      health states).
- [ ] 5.2 Registry rows → `implemented` with the merge; regenerate matrix
      (`tools/trace.py`).
- [ ] 5.3 Merge-gate checklist (commit-standard): full suites, trace, soup
      (no SOUP delta expected), manual sync, tiered review (small fleet +
      Codex), `--no-ff` merge, tag v0.6.0 + release notes.
