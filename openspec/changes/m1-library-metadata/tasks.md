# Tasks

## 1. Domain model and profiles (worktree area: library)

- [x] 1.1 Alembic migration: root_folders, series, issues, issue_files, format_profiles tables per design §1 (typed, sentinel-free, TEXT issue numbers, persisted ordering key) + default-profile data seed (idempotent) (FRG-SER-001, FRG-SER-002, FRG-QUAL-001, FRG-QUAL-002, FRG-DB-008)
- [x] 1.2 Repository layer: series/issue CRUD, `wanted_issues()` derived selectable (no wanted column — schema-inventory test), per-request statistics aggregates (FRG-SER-003, FRG-SER-004, FRG-SER-009)
- [x] 1.3 Root folders + safe path construction (`safe_path_component`, fixed M1 template, under-root validation, rename-with-rollback) (FRG-SER-008, FRG-NFR-012)
- [x] 1.4 Tagged tests: schema round-trips, two-level monitoring, wanted derivations (file add/remove, unreleased, unmonitored series), stats without recount, path safety incl. traversal fixtures (FRG-SER-001..004, 008, 009, FRG-QUAL-001, 002, FRG-NFR-012)

## 2. ComicVine client (worktree area: metadata)

- [x] 2.1 Typed client on the `external` factory profile: JSON+field_list, honest UA, typed exceptions, SecretStr key handling (FRG-META-001, FRG-META-002)
- [x] 2.2 Process-global rate limiter (2s default, clamp, Retry-After, ban-page fallback, degraded health flag) shared by all call sites (FRG-META-003, FRG-NFR-004)
- [x] 2.3 Pagination walk with complete=False partial results + hard page cap (FRG-META-004)
- [x] 2.4 Volume/issue mapping to typed dataclasses (None for absent, verbatim issue numbers, unnumbered-issue surfacing, element-count-wins) (FRG-META-005, FRG-META-006)
- [x] 2.5 Series search with plausibility annotations + publisher ignore-list (FRG-META-007)
- [x] 2.6 `sanitize_cv_text()` applied at ingest everywhere; sanitizing query-builder hook for downstream search (FRG-META-014, FRG-NFR-012)
- [x] 2.7 Cover cache (fetch via limiter+egress+byte cap; serve from disk; URL-change refetch; orphan cleanup) (FRG-META-013)
- [x] 2.8 Tagged tests on recorded fixtures: hung/429/malformed/5xx, key never in logs at debug, serialized wire times, partial pagination, mapping fixtures incl. hostile HTML, ban page; env-gated live smoke (FRG-META-001..008, 013, 014, FRG-NFR-004)

## 3. Library flows (worktree area: flows)

- [x] 3.1 Add flow: POST validation → series row with add_options → RefreshSeriesCommand chain (refresh → strategy-once+clear → scan → optional inert SeriesSearchCommand), restart-safe, job-history visible (FRG-SER-005, FRG-SER-006)
- [x] 3.2 Refresh reconciliation by cv_issue_id: insert per monitor_new_items, update, delete only on complete fetch, never-delete-with-files, single transaction + post-commit SeriesRefreshed (FRG-META-008, FRG-SER-007)
- [x] 3.3 Scan: match existing files to issues via the change-2 parser; record unmatched paths (no import routing) (FRG-SER-005)
- [x] 3.4 Edit/delete: PUT fields incl. path move; DELETE row-cascade keep-files; deleteFiles=true → 501 (FRG-SER-014)
- [x] 3.5 Tagged tests: full add chain on fixtures (incl. interrupted-chain resume), each monitor strategy, reconciliation matrix (add/update/delete/partial/with-files), scan matching on scratch copies of real filenames (FRG-SER-005..007, 014, FRG-META-008)

## 4. API surface (worktree area: api)

- [x] 4.1 Series router: list (envelope+sort whitelist), detail, POST (returns refresh command id), PUT, DELETE (501 for deleteFiles=true), `/series/lookup` (FRG-API-003, FRG-API-006)
- [x] 4.2 Issue router: list by seriesId ordered by ordering key (strings, never ints), single + atomic bulk monitored toggle (FRG-API-004)
- [x] 4.3 Command endpoint formalized: POST 201/400, GET list + by id, observable dedup (FRG-API-005)
- [x] 4.4 Cover endpoint serving from disk (404 when absent) (FRG-META-013)
- [x] 4.5 Tagged tests: envelope/sort-key 400s, lookup no-side-effects, add validation 400s, bulk atomicity, dedup observability (FRG-API-003..006)

## 5. Security docs, traceability, merge gate

- [x] 5.1 Risk register: RISK-011/014/019 mitigation status → implemented-by FRG-META-014/FRG-NFR-012; threat-model delta for the CV integration (FRG-PROC-006)
- [x] 5.2 Every in-scope FRG id has ≥1 passing tagged test; flip 28 registry rows to `implemented`; `tools/trace.py` exit 0 (FRG-PROC-004, FRG-PROC-005)
- [ ] 5.3 Suite green → /code-review (medium) → /simplify → suite + trace green → `--no-ff` merge → archive → update docs/process/decisions.md (FRG-PROC-007)
