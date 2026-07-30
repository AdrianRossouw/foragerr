# read-only-library — tasks

## 1. Read-only root (FRG-SER-021)

- [x] 1.1 Additive `read_only` column on the root-folder table + model
- [x] 1.2 Registration: RO root validates exists+readable (R_OK), waives
      W_OK; duplicate/nesting guards unchanged; `api/library_config.py`
- [x] 1.3 Central guard `root_is_read_only(...)` / `series_is_read_only(...)`
- [x] 1.4 Refuse fail-closed at every write path under a RO root: import
      placement, rescan moves, download-into, delete/recycle
- [x] 1.5 Tests: RO registration; each write path refused; a write-path
      audit test asserting zero on-disk change under a RO root

## 2. Index-in-place import (FRG-IMP-028)

- [x] 2.1 Import placement is a no-op for a RO root: register series at the
      existing folder, `issue_files` at real paths, no rename/move/copy
- [x] 2.2 Metadata + covers populate (DB / config dir only)
- [x] 2.3 Tests: index leaves files untouched; only DB/config-dir writes;
      failed index creates no series

## 3. Browse-only series + UI (FRG-SER-022, FRG-UI-045)

- [x] 3.1 RO series created unmonitored; monitor/search/grab/delete-files
      refuse with a clear reason; wanted/calendar acquisition surfaces
      exclude RO series
- [x] 3.2 OPDS + metadata refresh unchanged for RO series
- [x] 3.3 Frontend: root-folder read-only option; RO marker; hide/disable
      monitor/search/delete affordances; reading unaffected
- [x] 3.4 Tests: RO series serves but refuses acquisition (backend +
      vitest); no acquisition affordance rendered

## 4. Docs + verification

- [x] 4.1 `docs/manual/user/library.md` + `import.md` (registering a
      read-only library; what it does/doesn't do)
- [x] 4.2 Full backend (xdist) + frontend (serialized) green; soup 0; e2e
      green; trace picks up FRG-SER-021/022, FRG-IMP-028, FRG-UI-045
- [ ] 4.3 At-scale sanity on the rig against a real read-only collection
      (scan throughput, CV metadata budget) — record findings

## 5. Gate-fix hardening (8-angle + Codex gate on the change above)

A full-tier gate review found the write boundary above was incomplete:
the in-place import branch, post-placement archive rewrites, on-demand
convert, source-side confinement, and FK-vs-path derivation each had a
bypass. This section tracks closing them structurally rather than
per-endpoint.

- [ ] 5.1 Hoist the read-only guard above the in-place/move branch split
      in `pipeline.execute()` so disposal of an already-tracked file is
      refused in both branches, not only the move branch
- [ ] 5.2 Force ComicInfo tagging and CBR→CBZ conversion off (alongside
      `rename_enabled`) for a read-only root's series; guard both write
      sites so neither can be re-enabled for one
- [ ] 5.3 Guard `convert-series` / `convert-issue` (API + command-enqueue
      path) — the two `IMPORT_FILE_MUTATION_GROUP` commands that never
      routed through the guarded pipeline
- [ ] 5.4 Derive read-only status from the resolved path, not only the
      series' `root_folder_id`: scope add/edit path validation to the
      assigned root so a path inside a read-only root cannot register or
      move in under a writable root's id
- [ ] 5.5 Guard `grab-release` / `issue-search` command handlers (worker
      side) so a direct `POST /api/v1/command` enqueue cannot reach
      acquisition for a read-only series; re-check the boundary in
      `run_grab()` for source-entitlement acquisition before fetch/handoff
- [ ] 5.6 Refuse manual-import and `rescan-series` `path_override`
      candidates whose *resolved source path* lies under a read-only
      root in move mode, independent of the destination series' root.
      The read-only direction ONLY: `path_override` is deliberately not
      confined to the series' own root, because general FRG-SEC-004
      confinement would renegotiate FRG-SER-010 (whose scenario passes an
      override wholly outside every registered root, asserted in
      `backend/tests/library/test_rescan.py`). `path_override` therefore
      remains an authenticated arbitrary-directory walk-and-move
      primitive for any directory outside a read-only root; that residual
      is recorded on RISK-019, not closed here
- [ ] 5.7 Registry-level test: every command in `IMPORT_FILE_MUTATION_GROUP`
      consults the read-only guard, so a future mutating command added
      without it fails the test rather than shipping a silent gap
- [ ] 5.8 Frontend: gate the series Edit dialog and surface its errors;
      exclude read-only series from the calendar/pull projection
      (`_entries_for_issue_ids`) and gate its Want/Skip/Search controls;
      mark the read-only override in the Add Series root picker before
      submit; filter read-only series out of the rename picker
- [ ] 5.9 Unify `ReadOnlyRootError` into `ReadOnlySeriesError` and register
      the merged type with the 409 handler
- [ ] 5.10 Reject `recycle_bin_path` / `duplicate_dump_path` resolving
      under a read-only root — at submission (field-precise 400) AND at
      every point of consumption, since the submission check is bypassed
      by configuring the directory before the root is flagged read-only
      and by the env / `config.json` route; report a misconfigured
      disposal directory on the health surface. Case-fold the
      root-overlap comparison so a case-insensitive filesystem cannot
      register the same physical directory both read-only and writable
- [ ] 5.11 Tests for every item above; re-run the full gate (8 angles +
      Codex) before merge
