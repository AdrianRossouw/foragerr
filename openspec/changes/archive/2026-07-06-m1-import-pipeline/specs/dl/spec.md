## MODIFIED Requirements

### Requirement: FRG-DL-009 — Completed download handling

When a tracked item reports Completed, the system SHALL validate its (mapped) output path, resolve the series/issues from grab history or parsing — moving unresolvable items to ImportBlocked with a manual-interaction-required signal — and otherwise advance ImportPending → Importing → run the shared import pipeline → Imported when all grabbed issues imported, or back to ImportBlocked with per-file messages on partial/rejected import.

- **Milestone**: M1
- **Source**: sonarr-arch §4.5 (CompletedDownloadService)
- **Notes**: The import pipeline itself is the IMP area; this requirement owns the state transitions and the blocked-not-lost guarantee. Double post-processing cannot occur by construction: external completion scripts (Mylar's ComicRN) are excluded — CDH polling is the only intake (mylar-fs PP path 1 recommended as permanent exclusion).

#### Scenario: ProcessImports drains import-pending items through the shared pipeline to Imported

- **WHEN** the periodic ProcessImportsCommand (~1-minute cadence, running on the post-processing pool) drains a tracked download in state ImportPending whose mapped output path is valid and whose grabbed issues all resolve
- **THEN** the item is advanced to Importing, run through the one shared import pipeline (verify → aggregate → decide → rename-into-library via safe-join → issue_files row committed), transitioned to Imported once every grabbed issue is imported, and an import-history event is recorded for the download id

#### Scenario: Unresolvable completed item is blocked with a visible, persisted reason

- **WHEN** a completed item's series/issues cannot be resolved from grab history or title parsing
- **THEN** the item is moved to ImportBlocked carrying a manual-interaction-required signal and a human-readable reason, the reason is persisted and surfaced on the queue resource, and no file is auto-deleted or silently dropped

#### Scenario: Partial or rejected import blocks with per-file reasons and stays retryable

- **WHEN** the shared pipeline rejects some but not all grabbed issues (or all of them) during import
- **THEN** the item returns to ImportBlocked with per-file messages, the download and its staged evidence are retained (blocked-not-lost), and the item remains eligible for re-processing on a later ProcessImports run after user action or when the evidence changes

#### Scenario: Blocked item re-processes to Imported once evidence changes, without re-grab

- **WHEN** a previously ImportBlocked item's blocking condition is resolved (e.g. the operator supplies the mapping via manual import, or metadata now resolves the issue)
- **THEN** the next ProcessImports run re-processes the same retained download through the shared pipeline and advances it to Imported without requiring a fresh grab

### Requirement: FRG-DL-010 — Post-import client cleanup

After a download reaches Imported, the system SHALL remove the item (and its data) from the download client if and only if the per-client remove-completed-downloads flag is enabled.

- **Milestone**: M1
- **Source**: sonarr-arch §4.5 (DownloadEventHub)
- **Notes**: Mark-imported prevents reprocessing loops when cleanup is disabled.

#### Scenario: Successful import with remove-completed enabled removes the client item and data

- **WHEN** a download reaches Imported (its issue_files row committed) and the source client's remove-completed-downloads flag is enabled
- **THEN** the client's mark_imported/remove is invoked to delete the item and its data, and — for a DDL grab — the DDL staging files are removed only after that import success

#### Scenario: Successful import with remove-completed disabled marks imported but leaves the item

- **WHEN** a download reaches Imported and the source client's remove-completed-downloads flag is disabled
- **THEN** the client item is marked imported (so it is not re-processed) but neither the item, its data, nor its DDL staging files are removed

#### Scenario: Failed or blocked download is never cleaned from the client

- **WHEN** a tracked download is in ImportBlocked, FailedPending, or Failed rather than Imported
- **THEN** no client removal, mark_imported, or DDL staging cleanup occurs regardless of the remove-completed-downloads flag, so the source evidence remains available for retry
