# import-atomicity — tasks

## 1. Atomic per-group series (FRG-IMP-027)

- [x] 1.1 `_import_group`: track whether the series was created in THIS run
      (the add branch, not the reuse branch)
- [x] 1.2 On a group that attaches zero files (`refresh-failed`, post-add
      `errored`, blocked-with-zero-imported on a freshly created series):
      delete the group-created series via the existing series-delete path
      (files on disk untouched), after the staging-row reason is recorded
- [x] 1.3 Ensure any add-enqueued `search_on_add` command for a rolled-back
      series does not grab (cancel/dedupe, or verify the handler no-ops on
      a missing series)
- [x] 1.4 Never delete a reused / pre-existing series

## 2. Tests (FRG-IMP-027)

- [x] 2.1 refresh-failure after create → no series row, no monitored/wanted
      issues, no enqueued grab, staging row shows the reason
- [x] 2.2 genuinely-imported group unchanged (series + files kept)
- [x] 2.3 pre-existing/reused series never deleted by a failed group
- [x] 2.4 rolled-back group re-imports cleanly as a first run (no duplicate
      block)

## 3. Docs + verification

- [x] 3.1 `docs/manual/user/import.md` — a failed group leaves nothing
      half-added
- [x] 3.2 Full backend suite green; soup 0; trace picks up FRG-IMP-027
