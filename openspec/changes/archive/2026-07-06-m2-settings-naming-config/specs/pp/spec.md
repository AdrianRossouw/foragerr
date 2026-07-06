## MODIFIED Requirements

### Requirement: FRG-PP-012 — Rename preview before execution

The system SHALL compute and return existing-path → new-path rename previews for any series or file selection under the current templates without touching disk, and SHALL execute renames only as an explicit second step that emits per-file rename events.

- **Milestone**: M2
- **Source**: SA §5.4 (RenameEpisodeFileService preview/execute split); SA §8 Import bullet 3 ("previewable before execution").
- **Notes**: Applies to bulk re-organization of already-imported library files after a template change, not the initial import path (`pipeline.execute`, which names files directly). Same builder code as import naming — `build_fields` → `render_filename` → `safe_join` (design decisions 1–2). Execute recomputes the plan from `issue_files` rows rather than trusting a submitted plan, keeping preview and execute byte-identical. Tag test: `tests/importer/test_rename_ops.py`.

#### Scenario: Preview touches no disk

- **GIVEN** a fixture series with `issue_files` rows and a file template different from their current on-disk names
- **WHEN** `preview_renames(series, issue_files, ctx)` computes the plan
- **THEN** it returns a `(issue_file_id, current_path, new_path, changed)` entry per file and a filesystem spy (or pre/post directory-listing + mtime snapshot) confirms zero create/move/delete/write operations occurred.

#### Scenario: Execute performs exactly the previewed operations

- **GIVEN** a preview plan with two changed entries and one unchanged entry
- **WHEN** the execute step runs
- **THEN** exactly the two `current_path → new_path` moves are applied via `place_file`, no other path under the series folder is touched, the unchanged entry is skipped, and each moved file's `issue_files.path` is updated to its previewed `new_path`.

#### Scenario: One rename event per renamed file, in the same transaction

- **GIVEN** an execute over three files that all change
- **WHEN** it completes
- **THEN** three `EVENT_FILE_RENAMED` `import_history` rows are written inside the caller's write_session, each carrying the old and new path and the series/issue.

#### Scenario: Template change bulk preview marks no-ops unchanged

- **GIVEN** the global file template changes and some library files already match the new rendered name
- **WHEN** a preview is requested for the affected series
- **THEN** files already matching the new name are returned with `changed=false` and are excluded from execution; only differing files appear as operations.

#### Scenario: Every previewed name still round-trips

- **GIVEN** a preview computed under a newly edited template
- **WHEN** each proposed `new_path` basename is re-parsed by the single change-2 parser
- **THEN** it recovers the same series matching key and issue ordering key as the source `issue_files` row (a preview can never propose a name that breaks reconciliation — the FRG-PP-009 contract).

### Requirement: FRG-PP-013 — Upgrades and deletions via recycle bin

When an import replaces an existing file (upgrade) or a library file is deleted through the application, the displaced file SHALL be moved to a configured recycle-bin location (with collision-safe naming and scheduled cleanup) before the replacement lands, deleting permanently only when no recycle bin is configured.

- **Milestone**: M2
- **Source**: SA §5.3 (UpgradeMediaFileService, RecycleBinProvider), §6.1 (CleanRecycleBin 24h); SA §8 Import bullet 2.
- **Notes**: Replaces M1's `fileops.quarantine_file` stand-in with `recycle_file` behind the same execute seam (design decisions 4–7), keeping the collision-safe naming and cross-device copy-verify-delete fallback. Config: `recycle_bin_path` (`""` = permanent delete) and `recycle_bin_retention_days` (`0` = keep forever). Destination confinement-checked via `safe_join` (FRG-SEC-004). Tag test: `tests/importer/test_recycle_bin.py`.

#### Scenario: Upgrade recycles the replaced file

- **GIVEN** a configured `recycle_bin_path` and an existing library file for the target issue
- **WHEN** an upgrade import replaces it
- **THEN** the old file is moved to the recycle bin (collision-safe) before the new file lands, remains retrievable there, the new file is in place, and the `EVENT_UPGRADE_REPLACED` history row records the recycle path.

#### Scenario: No bin configured deletes permanently but records the event

- **GIVEN** `recycle_bin_path` is empty
- **WHEN** an upgrade import replaces an existing file
- **THEN** the old file is permanently deleted and the `EVENT_UPGRADE_REPLACED` history row still records the replacement with no recycle path.

#### Scenario: User deletion routes through the bin

- **GIVEN** a configured recycle bin and a library `issue_files` row
- **WHEN** the user deletes that file through the application
- **THEN** it is moved to the recycle bin (never hard-deleted) and an `EVENT_FILE_DELETED` history row records the recycle path.

#### Scenario: Retention pruning removes only aged entries

- **GIVEN** `recycle_bin_retention_days = N` with some bin entries older than N days and some newer
- **WHEN** the recycle-bin housekeeping prune runs
- **THEN** entries older than N days are permanently removed and newer ones are retained; with `recycle_bin_retention_days = 0` nothing is pruned.

#### Scenario: Existing quarantine files migrate without orphaning

- **GIVEN** files left under `<config>/quarantine/<date>/` by the M1 stand-in and a configured recycle bin
- **WHEN** the one-shot quarantine→recycle sweep runs
- **THEN** every quarantined file is moved into the recycle bin (none orphaned), the move is recorded on a history event, the sweep is idempotent on re-run, and with no bin configured the quarantine dir is left retired-in-place rather than deleted.

#### Scenario: Recycle destination is confined

- **GIVEN** a configured `recycle_bin_path`
- **WHEN** a file is recycled
- **THEN** its destination is constructed via `safe_join` under the bin root, and a source name engineered to traverse (`..`, absolute) cannot land outside the bin root (FRG-SEC-004).
