# m11-source-import-trust — tasks

## 1. Registry and parser (FRG-IMP-026)

- [x] 1.1 Allocate FRG-PP-021, FRG-PP-022, FRG-IMP-026, FRG-SRC-008,
      FRG-SRC-009 in docs/traceability/requirements-registry.md
      (status proposed→approved under the M11 standing grant, milestone
      M11); note MODIFIED FRG-PP-016 / FRG-SRC-006 (FRG-PROC-002)
- [x] 1.2 Parser filler stripping: consume anchored bare "Issue"/"Issues"
      before issue evidence so it never enters series_name; unit-safe for
      mid-title usage (FRG-IMP-026)
- [x] 1.3 Corpus rows appended (count assert bumped): SPAWN Vol. 243 /
      Spawn #211 / SPAWN Issue # 279 / Strangelands Issues #8 /
      Something is Killing the Children Vol. 8, tagged FRG-IMP-026 (+
      FRG-IMP-012 where volume semantics are pinned) (FRG-IMP-026)

## 2. Pipeline resolution (FRG-PP-021, FRG-PP-022)

- [x] 2.1 Split `_reconcile_base` step 2: series-only grab hint resolves
      issue within the provenance series; never falls through to
      unscoped step 3; honest series-scoped block reason (FRG-PP-021)
- [x] 2.2 Ordinal fallback: synthetic Issue(volume_ordinal) matched via
      the standard issue index when evidence.issue is None and the
      series is known (provenance + scoped-rescan branches); present
      issue evidence never overridden (FRG-PP-022)
- [x] 2.3 Tests: series-only hint import (the finding-#15 filename
      shapes), provenance-beats-parseable-other-series, ordinal lands /
      ordinal miss blocks / present-issue-miss blocks, tag precedence
      unchanged (FRG-PP-021, FRG-PP-022, FRG-PP-003 non-regression)

## 3. Manual-import state mirror (FRG-PP-016, FRG-SRC-006)

- [x] 3.1 Extract the drain's terminal-state aggregation; apply it in
      `execute_manual_import` via `_apply_state` (queue event emitted)
      for download-scoped executes (FRG-PP-016)
- [x] 3.2 Mirror source downloads on the manual path: call
      `apply_source_import` in the same write transaction for source
      download ids (FRG-SRC-006)
- [x] 3.3 Tests: humble-prefixed manual import flips tracked row +
      entitlement + owned-via-edition identically to the drain (shared
      fixture asserting path equivalence); mixed-outcome aggregation;
      folder imports unaffected (FRG-PP-016, FRG-SRC-006, FRG-SRC-007
      non-regression)

## 4. Review-proposal freshness (FRG-SRC-008)

- [x] 4.1 `add_entitlement`: pre-check cv_volume_id in library → delegate
      to match; narrow the catch-all 400 (FRG-SRC-008)
- [x] 4.2 Sibling sweep on successful add: rewrite same-volume proposals
      of `new` rows to library-kind match proposals in-transaction
      (FRG-SRC-008)
- [x] 4.3 Tests: add-degrades-to-match (no 400), sibling re-resolution,
      matched/ignored rows untouched, add-endpoint API test (first ever)
      (FRG-SRC-008)

## 5. Retry + health (FRG-SRC-009)

- [x] 5.1 `POST /sources/entitlements/{id}/retry-download`: failed-only
      (409 otherwise), clears error, re-queues via `_queue_grab`
      (FRG-SRC-009)
- [x] 5.2 Health: failed-source-download producer beside
      `_sources_component`, aggregated per source, remediation hint
      (FRG-SRC-009)
- [x] 5.3 Frontend: Retry button on failed entitlement rows + hook;
      screen test (FRG-SRC-009)
- [x] 5.4 Tests: retry happy path, non-failed 409, health degrade/clear
      (FRG-SRC-009)

## 6. Docs, gate, release

- [x] 6.1 Manual updates: sources section (retry, health warning,
      add-degrade), import section (Humble idioms resolve)
      (FRG-PROC-011)
- [x] 6.2 Traceability matrix regeneration; soup_check green (no dep
      changes expected) (FRG-PROC-005, FRG-PROC-012)
- [ ] 6.3 Medium-tier gate + Codex full-diff review, adversarial
      mis-match angle on FRG-PP-021/022; e2e via bash e2e/run.sh
      (FRG-PROC-004)
- [ ] 6.4 Live rig verification against findings #10/#15 reproductions
      (Strangelands + SPAWN entitlements on foragerr-test:8793)
- [ ] 6.5 Sync/archive spec deltas, flip registry rows to implemented,
      release v0.10.0 per /release (FRG-PROC-013)
