# ddl-optin-seeding — tasks

## 1. Seed flip

- [x] 1.1 Create branch `change/ddl-optin-seeding`; flip the two seed call
      sites in `backend/src/foragerr/db/first_run.py` to `enabled=False` with
      the indexer's automatic-search/RSS usage toggles off; update the seed
      log message (FRG-DEP-013)
- [x] 1.2 Update `backend/tests/test_first_run_seeding.py` (and any CRUD/API
      tests asserting the seeded rows' enabled state) to assert disabled rows
      with usage toggles off; keep no-resurrection / no-injection /
      never-Newznab-SAB assertions unchanged (FRG-DEP-013)
- [x] 1.3 Tagged test for the no-traffic scenario: with the seeded pair
      disabled and wanted issues present, the search/RSS/backlog candidate
      sets exclude the seeded provider and no DDL fetch is attempted
      (FRG-DEP-013)
- [x] 1.4 Tagged test for one-toggle activation: enabling both seeded rows via
      the API makes the pipeline behave identically to the old default-enabled
      posture (FRG-DEP-013)

## 2. e2e spine

- [x] 2.1 Add an explicit enable step (API `PUT` on both seeded rows) to the
      e2e spine after first-boot health, before the grab→download steps;
      assert the fresh container starts with the pair disabled (FRG-DEP-013,
      FRG-PROC-010)

## 3. Docs and risk posture

- [x] 3.1 Rewrite the `docs/manual/user/downloads.md` default-on passage:
      seeded pair ships disabled, enable steps (Settings → Indexers /
      Download Clients), and the rationale; sweep
      `docs/manual/admin/configuration.md` first-run description to match
      (FRG-PROC-011)
- [x] 3.2 Update RISK-015 and RISK-016 in `docs/security/risk-register.md`:
      posture returns to opt-in; record the 2026-07-09 fresh-install
      auto-grab incident as the triggering event; adjust review triggers
      (FRG-PROC-006)

## 4. Merge gate

- [ ] 4.1 Full merge-gate checklist per `docs/process/commit-standard.md`
      (suite green, soup_check 0, trace clean, history-scan ancestry,
      CHANGELOG + version bump v0.3.5, release notes) (FRG-PROC-007,
      FRG-PROC-013, FRG-PROC-015)
- [ ] 4.2 Pre-merge review cycle on the branch
- [ ] 4.3 Sync delta spec to baseline, archive change, regenerate matrix;
      merge `--no-ff`, tag, publish release
