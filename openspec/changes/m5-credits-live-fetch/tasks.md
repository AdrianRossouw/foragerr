# Tasks — m5-credits-live-fetch

## 1. Backend

- [ ] 1.1 `get_issue_credits(issue_id)` on the CV client (minimal
      field_list, typed errors); migration 0017
      `issues.credits_fetched_at` + index (FRG-CRTR-001, FRG-CRTR-002)
- [ ] 1.2 Bounded newest-first fetch phase in `refresh_series` (CV I/O
      outside the lock; stamp + reconcile inside; failure = retry-later);
      `credits_fetch_per_refresh` config (default 25, clamped)
      (FRG-CRTR-001)
- [ ] 1.3 Tagged tests: bound + ordering + gate usage, zero-credit stamp,
      failed-fetch retry eligibility, idempotent re-reconcile, existing
      CRTR suites green (FRG-CRTR-001, FRG-CRTR-002)
- [ ] 1.4 Anti-masking fixtures: list serves null credits, detail serves
      credits, tripwire test pinning the pair (FRG-CRTR-001)

## 2. Docs, tour, gate

- [ ] 2.1 README Creators section + creators-grid shot restored (capture
      script re-adds the shot; refresh tour) (FRG-PROC-011/017)
- [ ] 2.2 CHANGELOG v0.5.3 + bump on-branch; matrix regen; suites + e2e
      green; small-medium gate + Codex; keystore coordination check
      (0017 claimed → they take 0018) (FRG-PROC-005/007/013)
