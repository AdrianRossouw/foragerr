## MODIFIED Requirements

### Requirement: FRG-PP-016 — Manual import resolution

The system SHALL provide a manual import view listing candidate files (from an import-blocked download or an arbitrary folder) with their would-be decisions and rejection reasons, allowing the user to override series, issue, and format per file and then execute those files through the shared import pipeline.

- **Milestone**: M2
- **Source**: SA §5.5 (ManualImportService — "the escape hatch for every mapping failure"), §4.5 (ImportBlocked → ManualInteractionRequiredEvent); MFS §4 (manual PP of arbitrary folder).
- **Notes**: The resolution path the M1 import-blocked state points at. Executes through the SAME `import_candidate` (one `aggregate → decide → execute`); a `ManualImportSource` produces neutral `ImportCandidate`s (reusing `CompletedDownloadSource.gather` for the blocked-download entry point, an unscoped folder walk for the ad-hoc entry point); overrides enter as the top-priority reconciliation layer and bypass ONLY the series/issue mapping specs.

#### Scenario: Blocked download resolved by override through the shared pipeline

- **WHEN** an `import_blocked` download whose file failed automatic mapping is listed via manual import, and the user submits a series/issue override for that file
- **THEN** the override pins `(series_id, issue_id)` at the reconciliation seam, `import_candidate` runs the full spec set over the pinned evaluation, the file imports via `execute`, and the same `imported` history event and `issue_files` row are written as an automatic import — with no separate manual code path.

#### Scenario: Arbitrary folder of unmatched files

- **WHEN** manual import is opened on an arbitrary folder of archives that carry no grab record
- **THEN** each file is walked with the same bounded `iter_archive_files` intake, aggregated and decided so its would-be verdict and reasons show, and a per-file override drives it through `import_candidate` to the correct issue.

#### Scenario: Override bypasses mapping but NOT the safety specs

- **WHEN** a user overrides series/issue for a file whose archive is corrupt (or which is below the junk-size floor, or whose destination volume lacks free space)
- **THEN** the mapping specs are satisfied by the override but `ArchiveValidSpec` / `JunkFilterSpec` / `FreeSpaceSpec` still evaluate and reject, so the file is NOT force-imported and its verdict lists the real blocking reason.

#### Scenario: Override to a non-existent entity is not trusted

- **WHEN** a submitted override names a `series_id`/`issue_id` that does not exist, or an issue that does not belong to the chosen series
- **THEN** the override is dropped rather than fabricating a mapping, the candidate falls back to the normal heuristic, and if it still cannot resolve it stays blocked with a visible reason — never imported to a phantom entity.

#### Scenario: Failed manual candidate stays listed, not lost

- **WHEN** a manually-submitted file fails during execution (e.g. an IO error placing the file)
- **THEN** it is parked BLOCKED with a visible reason (never FAILED-blocklisted for an environmental error, never auto-deleted), and it remains available in the manual-import listing for another attempt.

### Requirement: FRG-PP-017 — ComicInfo.xml tagging on import

When tagging is enabled, the import pipeline SHALL write ComicInfo.xml metadata (series, issue number, title, volume, cover date, publisher, ComicVine issue ID, story-arc fields where known) into cbz archives in-process during import, sourced from the matched ComicVine issue record, without shelling out to an external ComicTagger installation.

- **Milestone**: M2
- **Source**: MFS §4 Metadata tagging (cmtagmylar subprocess flow — behavior to keep, subprocess mechanism to drop); MFS §8 bullet 3.
- **Notes**: In-process zip rewrite. Runs AFTER the file is placed and the `imported` event recorded; a tagging failure never fails the import (file lands untagged + warning event). Rewrites ONLY cbz archives whose `inspect_archive` report has `safe_to_extract=True`; streams members to a temp zip (re-checking each member name), never extracts to disk, and atomically replaces. Off by default (`comicinfo_tag_on_import`).

#### Scenario: Enabled tagging writes a schema-valid ComicInfo.xml

- **WHEN** tagging is enabled and a cbz that passes inspection imports for a matched issue
- **THEN** the resulting archive contains a single root-level `ComicInfo.xml` whose Series/Number/Title/Volume/cover-date/Publisher/ComicVine-id fields match the library issue record, built from the record (not from any untrusted input), and the file otherwise imports normally.

#### Scenario: Disabled tagging leaves the archive untouched

- **WHEN** tagging is disabled
- **THEN** the import succeeds and the archive bytes are unchanged — no rewrite is attempted and no temp zip is produced.

#### Scenario: Hostile member name in the source cbz

- **WHEN** the source cbz contains a member whose name is absolute or carries a `..`/separator escape
- **THEN** the archive fails `inspect_archive` (`safe_to_extract` is false) so no rewrite is attempted; and even on the streaming copy path every member name is re-checked, so a hostile name is refused/skipped and never written to a traversed path.

#### Scenario: Oversized ComicInfo source metadata is bounded

- **WHEN** building/rewriting encounters an existing ComicInfo member (or any member) whose declared size exceeds the per-member cap
- **THEN** the operation stays within the shared archive limits — the oversized existing ComicInfo is not read into memory unbounded — and tagging degrades to a warning rather than a resource blow-up.

#### Scenario: Rewrite failure leaves the original intact

- **WHEN** the in-process rewrite raises partway (disk full, IO error, or a member that fails re-validation)
- **THEN** the temp zip is unlinked and the placed library file remains byte-identical and fully imported; a `comicinfo_tag_failed` warning event is recorded and the import is NOT failed.
