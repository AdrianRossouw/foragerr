# Tasks — m5-creators-backbone

## 1. Ingest and mapping

- [x] 1.1 Add `person_credits` to `ISSUE_FIELDS`; extend `IssueRecord` +
      `map_issue` with typed credit entries (sanitized name, verbatim +
      normalized role, person id); total mapping — malformed/absent credits
      → empty list (FRG-CRTR-001, FRG-META-006)
- [x] 1.2 Role-normalization vocabulary + splitter with tagged tests incl.
      compound roles, unknown roles, hostile strings through
      `sanitize_cv_text` (FRG-CRTR-001)

## 2. Storage and reconciliation

- [x] 2.1 Migration 0016: `creators`, `issue_credits` (+ indexes), one-time
      backfill marker; forward-only pattern per 0015 (FRG-CRTR-002)
- [x] 2.2 `creators/` package: models, repo, per-issue credit-set replace in
      `_reconcile`, creator upsert, prune (never-touched-only), threshold
      seeding after reconcile (FRG-CRTR-002, FRG-CRTR-004)
- [x] 2.3 Tagged tests: idempotent re-refresh, credit removal, partial-fetch
      deletion skip, cascade, prune vs touched/followed survival, seeding at
      ≥2 distinct series, user-toggle never overwritten (FRG-CRTR-002,
      FRG-CRTR-004)

## 3. Backfill and API

- [x] 3.1 `creators-backfill` command: dedup fan-out over `refresh-series`,
      one-time startup trigger via marker, force-runnable, job history;
      tagged tests incl. marker one-shot + manual re-run (FRG-CRTR-003)
- [x] 3.2 `api/creators.py`: paged list with aggregates + bounded work refs,
      profile detail, follow toggle PUT; wired into the router; tagged API
      tests incl. no-CV-request assertion and sanitized-output check
      (FRG-API-023, FRG-CRTR-004)

## 4. Docs, traceability, gate

- [x] 4.1 RISK-011 ingest-arm note (credits strings through the sanitizer);
      registry flips to implemented; matrix regen; soup_check green
      (FRG-PROC-002/005/006)
- [x] 4.2 CHANGELOG + version bump on-branch (v0.5.0 — M5 opens); full
      suites + e2e green; tiered gate (medium) + Codex; coordination check
      against the keystore branch (migration number, registry, decisions.md)
      before merge (FRG-PROC-007/013)
