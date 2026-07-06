## MODIFIED Requirements

### Requirement: FRG-SER-010 — Per-series disk rescan

The system SHALL provide a per-series rescan command that re-enumerates files under the series path, removes issue-file records whose files vanished, and routes unmatched files through the shared import pipeline.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §5.5 (DiskScanService, shared pipeline); mylar-feature-surface.md capability map SER (forceRescan).
- **Notes**: The import pipeline itself is the IMP/PP area's requirement; SER owns the trigger, cleanup of vanished files, and statistics refresh. Runs automatically after metadata refresh and on demand.

#### Scenario: RescanSeries walks the series path and routes untracked files through the shared pipeline

- **WHEN** RescanSeriesCommand runs for a series and enumerates files under its (possibly overridden) path to a bounded depth using the shared extension list
- **THEN** files already linked to an issue-file record are skipped and every remaining file is routed through the same shared import pipeline used by completed-download handling, with no separate rescan-only import path

#### Scenario: Vanished files are cleared and the issue returns to Wanted

- **WHEN** a file backing an existing issue-file record no longer exists on disk at rescan time
- **THEN** that issue-file record is removed and the now-fileless monitored issue returns to the derived Wanted state

#### Scenario: A correctly named dropped-in file is linked and stats update immediately

- **WHEN** a correctly named file is dropped into the series folder and a rescan is run
- **THEN** the file is matched and a new issue_files row is created, and per-series statistics (have/total, size on disk) reflect the new record immediately via derivation with no manual recount

#### Scenario: Unmatched or blocked files are recorded in a per-series rescan report

- **WHEN** a rescanned file cannot be matched to an issue or is rejected by the shared pipeline
- **THEN** it is recorded in a per-series rescan report with its reason rather than silently ignored, leaving the file in place for the operator to resolve
