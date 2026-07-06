# Tasks

## 1. Safety utilities (worktree area: security)

- [ ] 1.1 `security/paths.py`: safe_join(root, *parts) with realpath containment; relocate safe_path_component here (single ownership); traversal property-test corpus (FRG-SEC-004)
- [ ] 1.2 `security/archives.py`: inspect_archive with configurable limits (member count, per-member/total decompressed size, nesting 0), slip/symlink/absolute rejection, cbz≥1-image check, cbr magic+listing; committed hostile corpus tests (FRG-SEC-003, FRG-PP-006)

## 2. Pipeline core (worktree area: importer)

- [ ] 2.1 Pipeline stages gather → aggregate → decide → execute with sources-as-data (CompletedDownloadSource, RescanSource); single decide/execute audit test (FRG-PP-001)
- [ ] 2.2 Evidence aggregation via the single parser in confidence order with per-field provenance; issue-id tag short-circuit (FRG-PP-003, FRG-PP-004)
- [ ] 2.3 Decision specs (mapped, archive-valid, free-space, junk filter, upgrade-per-profile), all-run with visible reasons; import_blocked persistence (FRG-PP-005)
- [ ] 2.4 Safe file ops (rename/copy-verify-delete, margin check, no partials) (FRG-PP-007)
- [ ] 2.5 Remote path mapping application + unmapped → blocked with reason (FRG-PP-008)
- [ ] 2.6 import_history events in-transaction, queryable per issue/globally (FRG-PP-011)
- [ ] 2.7 Tagged tests: per-spec matrices, provenance recording, cross-device fallback, interrupted-transfer cleanliness (FRG-PP-001, 003..008, 011)

## 3. Renaming engine (worktree area: renamer)

- [ ] 3.1 Token template engine (tokens, padding, optional groups, case control, byte-aware truncation, disable switch); folder templates via safe_join; empty-dir cleanup; quarantine-on-upgrade (FRG-PP-009, FRG-PP-010)
- [ ] 3.2 Round-trip property test: every rendered name re-parses to the same matching key + ordering key over the corpus identities (FRG-PP-009)
- [ ] 3.3 SER-008 template ownership transfer: change-3 fixed template now rendered by this engine (no behavior change for existing rows) (FRG-PP-010)

## 4. Completion of parked requirements (worktree area: flows)

- [ ] 4.1 ProcessImportsCommand drains import_pending → Importing → Imported / import_blocked-with-reasons; blocked items retryable, re-processed on evidence change (FRG-DL-009, FRG-PP-002)
- [ ] 4.2 Post-import client cleanup gated on imported + per-client flag; DDL staging cleanup only after success; mark_imported prevents reprocessing (FRG-DL-010)
- [ ] 4.3 RescanSeriesCommand: bounded walk, vanished-file cleanup → wanted restoration, unmatched via pipeline, per-series report, derived stats (FRG-SER-010)
- [ ] 4.4 Tagged tests: full grab→import E2E on scratch copies of real-library samples, blocked-not-lost matrix, cleanup gating, rescan matrix (FRG-DL-009, FRG-DL-010, FRG-SER-010, FRG-PP-002)

## 5. Security docs, traceability, merge gate

- [ ] 5.1 Risk register: RISK-005/008/010 (archive safety), RISK-019/029 (confinement) → mitigation status; STRIDE delta; unrar-absent CBR-depth residual noted (FRG-PROC-006)
- [ ] 5.2 All 16 ids tagged-tested; registry flip; trace.py exit 0 (FRG-PROC-004, FRG-PROC-005)
- [ ] 5.3 Suite green → /code-review → /simplify → merge --no-ff → archive → decision-index update (FRG-PROC-007)
