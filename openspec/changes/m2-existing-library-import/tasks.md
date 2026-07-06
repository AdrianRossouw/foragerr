## 1. Walk + reconciliation (FRG-IMP-022)

- [ ] 1.1 Junk predicates (AppleDouble/`@eaDir` dirs, `._` files, dotfiles,
      zero-byte, unpack-temp dirs) applied inside `iter_archive_files`; all
      existing consumers inherit. Tests incl. uppercase extension + junk tree.
      [FRG-IMP-022]
- [ ] 1.2 Generalize vanished-file reconciliation from `flows/rescan.py` to
      root-scope scan (shared helper; rescan keeps behavior). Tests: deleted
      file's row removed before staging. [FRG-IMP-022]
- [ ] 1.3 Depth-bound + race tolerance pinned by tests (vanishing entry mid-walk
      does not fail the scan). [FRG-IMP-022]

## 2. Staging + scan command (FRG-IMP-023)

- [ ] 2.1 Migration: `library_import_groups` table (matching_key, root_folder_id,
      folder, files JSON, confidence, proposed/confirmed cv_volume_id, state,
      scanned_at). [FRG-IMP-023]
- [ ] 2.2 `library-import-scan` command (pp pool, NOT file-mutating): walk →
      reconcile → parse/group by `matching_key` (folder+file evidence) →
      propose CV match per group via `search_series` + plausibility floor
      (cap N proposals/run, log the cut) → upsert staging atomically per root.
      [FRG-IMP-023]
- [ ] 2.3 `LibraryImportSource` (ManualImportSource shape): yields a confirmed
      group's files with series pinned via override; safety specs unaffected.
      [FRG-IMP-023]
- [ ] 2.4 `library-import` execute command (IMPORT_FILE_MUTATION_GROUP): per
      group — `add_series` (path_override=folder when in_place) → source →
      `import_candidate` loop → staging state transitions
      (imported/blocked visible). Re-check = re-scan semantics. [FRG-IMP-023]
- [ ] 2.5 Wire `library_import_mode`: in-place registers existing paths without
      `place_file` (rename-disabled semantics honored); move routes through
      normal placement. Tests both modes. [FRG-IMP-023]

## 3. Duplicate constraint (FRG-PP-014)

- [x] 3.1 Parser: `(fN)` fixed-release marker annotation on `ParseResult` +
      corpus rows (incl. a title-plausibility guard case). [FRG-PP-014]
- [x] 3.2 `DuplicateConstraintSpec` arbitrating ONLY same-rung ties:
      markers first, then `duplicate_constraint` (`larger-size` default,
      `preferred-format`); history reason recorded. Upgrade/downgrade behavior
      byte-identical to before (tests pin). [FRG-PP-014]
- [x] 3.3 Dump-folder disposal in `execute`'s replaced-file branch:
      `duplicate_dump_path` dated subdirs, collision-suffixed, unmarked root
      (recycle prune never touches it — test). Config fields + config resource
      + settings UI + documented config regen. [FRG-PP-014]

## 4. API (FRG-IMP-023 surface)

- [ ] 4.1 `POST /api/v1/library-import/scan`, `GET /api/v1/library-import`
      (paged), `PATCH /api/v1/library-import/groups/{id}`
      (confirm/override/skip; override CV-validated), `POST
      /api/v1/library-import/execute` (groups + batch add options) — 201
      CommandResource pattern, errors per ApiError conventions. Tests tagged
      FRG-IMP-023. [FRG-IMP-023]

## 5. UI (FRG-UI-015)

- [ ] 5.1 Library Import screen: root picker, scan trigger + running state
      (command polling), group cards (folder, count, confidence, proposal
      poster/year/publisher, no-match state), inline lookup correction,
      selection + batch add options, per-group outcomes with reasons; explicit
      unconfigured/empty states. Route + sidebar. Vitest FRG-UI-015 named
      tests incl. negative states. [FRG-UI-015]

## 6. Docs, security, traceability, gate

- [ ] 6.1 Manual: new user section (library import flow, in_place vs move),
      media-management settings additions (duplicate constraint, dump folder).
      [FRG-PROC-011]
- [ ] 6.2 Security docs delta: scan/execute endpoints take root_folder_id only
      (no raw paths) — note under FRG-SEC-004 posture; risk register reviewed,
      no new listener/credential. [FRG-PROC-006]
- [ ] 6.3 Registry flip to implemented (IMP-022, IMP-023, UI-015, PP-014) +
      matrix regen + soup check 0. [FRG-PROC-004, FRG-PROC-005]
- [ ] 6.4 e2e: extend the spine (or a scenario) with a minimal library-import
      pass over a fixture folder (add negative: scan with no roots configured).
      [FRG-PROC-010]
- [ ] 6.5 Suites green; 8-angle + Codex gate; fixes; archive; --no-ff merge;
      main suites; tag v0.2.3. [FRG-PROC-007]
