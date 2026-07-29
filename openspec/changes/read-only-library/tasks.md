# read-only-library — tasks

## 1. Read-only root (FRG-SER-021)

- [ ] 1.1 Additive `read_only` column on the root-folder table + model
- [ ] 1.2 Registration: RO root validates exists+readable (R_OK), waives
      W_OK; duplicate/nesting guards unchanged; `api/library_config.py`
- [ ] 1.3 Central guard `root_is_read_only(...)` / `series_is_read_only(...)`
- [ ] 1.4 Refuse fail-closed at every write path under a RO root: import
      placement, rescan moves, download-into, delete/recycle
- [ ] 1.5 Tests: RO registration; each write path refused; a write-path
      audit test asserting zero on-disk change under a RO root

## 2. Index-in-place import (FRG-IMP-028)

- [ ] 2.1 Import placement is a no-op for a RO root: register series at the
      existing folder, `issue_files` at real paths, no rename/move/copy
- [ ] 2.2 Metadata + covers populate (DB / config dir only)
- [ ] 2.3 Tests: index leaves files untouched; only DB/config-dir writes;
      failed index creates no series

## 3. Browse-only series + UI (FRG-SER-022, FRG-UI-045)

- [ ] 3.1 RO series created unmonitored; monitor/search/grab/delete-files
      refuse with a clear reason; wanted/calendar acquisition surfaces
      exclude RO series
- [ ] 3.2 OPDS + metadata refresh unchanged for RO series
- [ ] 3.3 Frontend: root-folder read-only option; RO marker; hide/disable
      monitor/search/delete affordances; reading unaffected
- [ ] 3.4 Tests: RO series serves but refuses acquisition (backend +
      vitest); no acquisition affordance rendered

## 4. Docs + verification

- [ ] 4.1 `docs/manual/user/library.md` + `import.md` (registering a
      read-only library; what it does/doesn't do)
- [ ] 4.2 Full backend (xdist) + frontend (serialized) green; soup 0; e2e
      green; trace picks up FRG-SER-021/022, FRG-IMP-028, FRG-UI-045
- [ ] 4.3 At-scale sanity on the rig against a real read-only collection
      (scan throughput, CV metadata budget) — record findings
