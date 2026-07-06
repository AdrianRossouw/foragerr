# imp — delta for m2-existing-library-import

## MODIFIED Requirements

### Requirement: FRG-IMP-022 — Library scan walk

The library scanner SHALL recursively enumerate comic files under configured root/series paths, recognizing extensions case-insensitively and skipping junk (AppleDouble/`@eaDir` dirs, `._` resource forks, dotfiles, `_unpack_`-prefixed temp folders), and SHALL reconcile the database against disk by removing file records whose files have vanished before evaluating unmapped files. Zero-byte files are NOT silently skipped at walk time: they enumerate and are rejected visibly at decision time (the junk-size floor), preserving the visible-blocked guarantee for truncated payloads.

- **Milestone**: M2
- **Source**: MFP §2.1 (directory walk skips); SA §5.5 (DiskScanService, MediaFileTableCleanupService); MFS capability map IMP (recursive library scan).
- **Notes**: Per-series rescan is the same walk scoped to one series path (`forceRescan` analogue, MFS §8). Unmapped files feed the shared import pipeline (see PP shared-pipeline requirement) — the scanner itself makes no import decisions. Junk skipping lives in the shared `iter_archive_files` walk so every consumer (rescan, manual import, library import) inherits it; the DB-vs-disk vanished-file reconciliation generalizes the per-series rescan mechanism to root scope.

#### Scenario: Junk artifacts are skipped by the shared walk

- **WHEN** a scanned tree contains AppleDouble/`@eaDir` directories, `._` resource-fork files, dotfiles, zero-byte archives, and an unpack-temp folder (`_UNPACK_`-prefixed) alongside real archives including one with an uppercase extension
- **THEN** the walk yields the real archives (uppercase extension recognized) plus the zero-byte archive (surfaced as a visible decision-time rejection, never silently dropped), skips the dot/AppleDouble artifacts, and never descends into the junk/unpack directories — a user folder that merely starts with `_unpack` but lacks the trailing underscore (e.g. `_unpacked extras`) is walked normally

#### Scenario: Vanished files are reconciled before unmapped evaluation

- **WHEN** a root-folder scan runs after files backing existing `issue_files` rows were deleted on disk
- **THEN** those rows are removed (their issues revert to file-less) before unmapped files are staged, so a stale DB record never blocks re-import of a replacement file

#### Scenario: Scan is bounded and race-tolerant

- **WHEN** a scan encounters a directory deeper than the configured max walk depth, or a file that disappears between listing and stat
- **THEN** the walk stops descending at the bound and skips the vanished entry without failing the scan

### Requirement: FRG-IMP-023 — Existing-library import staging and review

The system SHALL stage library-scan parse results grouped by normalized series name into a reviewable import queue, presenting per-group would-be matches with parse confidence, and SHALL support mass import, per-group selection/override, and re-check before committing files to the library.

- **Milestone**: M2
- **Source**: MFS §4 Library import (librarysync staging, import UI); SA §5.5 (manual import as the override escape hatch); MFP §5 (structured output powers the review UI).
- **Notes**: ComicVine identification search for unmatched groups belongs to the metadata AREA; this requirement covers staging/review mechanics. Optional move/rename-on-import reuses the PP renaming engine — no second file-ops path; `library_import_mode` (`in_place` default vs `move`) is consumed at the shared pipeline's placement seam. Groups key on the parser's shared `matching_key` normalization (the same folding `SeriesRow.matching_key` uses). Import executes through the SAME `import_candidate` pipeline; a `LibraryImportSource` follows `ManualImportSource`'s shape and its candidates carry the group's confirmed series mapping as overrides — safety specs still evaluate.

#### Scenario: Scan stages groups keyed by normalized series name

- **WHEN** a root-folder scan walks a library of several series folders with parseable filenames
- **THEN** unmapped files are parsed and staged grouped by `matching_key`, each group carrying its file list, folder name, parse confidence, and a proposed ComicVine match (or none) — and the staging is persisted so the review survives a restart

#### Scenario: Mass import with per-group override and re-check

- **WHEN** the user selects groups (selecting a proposed group with an attached match counts as confirming it), overrides the ComicVine match on one ambiguous group, deselects another, and triggers import
- **THEN** selected groups create their series and run their files through the shared `import_candidate` pipeline (same specs, same history events); the overridden group uses the corrected volume (an override becomes the group's proposal, so what the card displays is always what imports); the deselected group stays staged; per-file blocked reasons persist on the group verbatim; and a re-check re-evaluates staged groups against the now-larger library without duplicating already-imported files — two selected groups confirmed to the same volume are rejected up front, and a group whose volume already exists in the library never has its files moved out of their folder

#### Scenario: In-place import registers files without moving them

- **WHEN** `library_import_mode` is `in_place` (default) and a confirmed group's files already live under the series' folder-to-be
- **THEN** imported files are registered (`issue_files` rows, `hasFile`) at their existing paths — no move, copy, or rename occurs; with `move`, files route through the normal placement/rename path instead

#### Scenario: Unparseable or unmatched groups stay reviewable, never silently dropped

- **WHEN** a scanned folder yields files whose parse fails or whose group has no plausible ComicVine match
- **THEN** the group is staged with its failure/no-match state visible for manual resolution, and mass import skips it rather than importing to a guessed series
