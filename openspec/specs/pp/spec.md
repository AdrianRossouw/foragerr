# PP — Post-Processing Specification

## Purpose

Baseline requirements for post-processing, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).
## Requirements
### Requirement: FRG-PP-001 — Single shared import pipeline

Completed-download import, existing-library scan import, and manual import SHALL execute one shared import pipeline (evidence aggregation → import decisions → import execution), differing only in input source and a new-download flag — with no per-path forks of decision or file-op logic.

- **Milestone**: M1
- **Source**: SA §5.5 ("library import and download import share one pipeline — major simplification worth copying"); SA §8 Import/files bullet 1.
- **Notes**: This is the structural keystone of the AREA; every following requirement hangs off it. Deliberate divergence from Mylar's four separately-coded intake paths (MFS §4).

#### Scenario: Both M1 sources drive the same stages

- **WHEN** a CompletedDownloadSource supplies tracked_downloads from import_pending and a RescanSource supplies files from a series-path walk
- **THEN** both are consumed as data by the identical gather → aggregate(Evidence) → decide → execute stages, running the same ordered specs and writing the same import_history rows.

#### Scenario: Single decision/execution implementation

- **WHEN** a code audit inspects the pipeline for the two M1 sources
- **THEN** there is exactly one decide() and one execute() implementation, with the source (CompletedDownloadSource vs RescanSource) represented as data and no per-source fork of decision logic or file operations.

#### Scenario: Reasons visible regardless of source

- **WHEN** the decision stage runs for either source
- **THEN** every ordered spec runs and each accept/reject carries a user-visible reason attached to the candidate file.

### Requirement: FRG-PP-002 — Completed-download handling state machine

The system SHALL poll download clients (SABnzbd, built-in DDL) on a ~1-minute tracking loop, match items to grab history, and maintain a per-download state machine — downloading → import pending → importing → imported, with failed-pending → failed and import-blocked (manual interaction required) branches — that backs the visible queue, with no external client-side completion scripts required.

- **Milestone**: M1
- **Source**: SA §4.4–4.5 (DownloadMonitoringService, CompletedDownloadService, TrackedDownload states); MFS §4 pickup path 2 (CDH); SA §8 Downloading bullets 2–3.
- **Notes**: Deliberate divergence: Mylar's ComicRN.py external-script path and watched-folder monitor are dropped — CDH polling is the only automatic intake (plus manual import). Post-import removal from the client is gated by a per-client remove-completed flag (SA §4.5). Check (fast) vs process (slow) separation is a design hint, not a requirement.

#### Scenario: ProcessImportsCommand drains import_pending

- **WHEN** ProcessImportsCommand runs on the pp pool on its ~1-minute cadence
- **THEN** it drains items in import_pending, advancing each per-download through downloading → import pending → importing → imported with the queue state observable at each step, and requires no external client-side completion script.

#### Scenario: Unresolvable download blocks, never lost

- **WHEN** a completed download cannot be resolved by the pipeline
- **THEN** it enters the import-blocked (manual interaction required) branch with a user-visible message, and is neither auto-deleted nor silently dropped.

#### Scenario: Corrupt/failed archive takes the failed branch

- **WHEN** a tracked download's file fails verification during processing
- **THEN** it transitions failed-pending → failed rather than importing.

### Requirement: FRG-PP-003 — Grab reconciliation by download ID

Every grab SHALL record a history row keyed by the download-client ID, and completed downloads SHALL be reconciled to their grabbed issues primarily by that ID, falling back to parsing the download title/folder name (via the single IMP parser, including the `[__issueid__]` tag for DDL) only when no history match exists.

- **Milestone**: M1
- **Source**: SA §4.3 ("DownloadId is the join key for the entire rest of the pipeline"); MFS §4 snatch↔download handshake (nzblog analogue); SA §8 Downloading bullet 2.
- **Notes**: Replaces Mylar's name-normalized `nzblog` matching (AltNZBName fragility) with Sonarr's ID join; the parse fallback covers Mylar's `mode='outside'` case.

#### Scenario: Download-ID match survives an unparseable name

- **WHEN** a completed download has a grab_history row for its download_id but its folder/title is unparseable
- **THEN** it reconciles to the grabbed issue via the download_id join and imports correctly.

#### Scenario: Parser fallback when no history match

- **WHEN** a completed download has no grab_history match for its download_id
- **THEN** the pipeline falls back to parsing the title/folder name via the single change-2 parser, and lands the item in import_blocked if that too fails to resolve.

#### Scenario: Issue-id tag short-circuits to direct lookup

- **WHEN** a download name carries a `[__issueid__]` tag (DDL convention)
- **THEN** reconciliation short-circuits to a direct issue lookup by that id.

### Requirement: FRG-PP-004 — Import evidence aggregation

For each candidate file, the import pipeline SHALL aggregate parse evidence from the file name, the containing folder name, the download-client item title, embedded archive metadata where read, and the grab record, selecting per-field values by a defined source-confidence order and recording which source supplied each field.

- **Milestone**: M1
- **Source**: SA §5.1 (AggregationService: file/folder/client-title evidence, grab record by DownloadId); MFP §5 (folder-vs-filename provenance); SA §8 Import bullet 1.
- **Notes**: All evidence parsing goes through the single IMP parser. Confidence signals from the parser (IMP structured-result requirement) are the aggregation inputs.

#### Scenario: Single parser and defined source order

- **WHEN** evidence is aggregated for a candidate file
- **THEN** every layer is parsed only through the single change-2 parser, and per-field values are selected by the order grab record > `[__issueid__]` tag > file name > folder name (folder mode) > client title.

#### Scenario: Junk filename overridden by better sources with recorded provenance

- **WHEN** the file name is junk but the folder name and grab record are good
- **THEN** aggregation resolves to the correct issue and the decision trace records, per field, which source supplied the value.

### Requirement: FRG-PP-005 — Import decision specifications with visible reasons

Each candidate file SHALL pass through an ordered set of accept/reject import specifications — at minimum: maps to a known series/issue, genuinely an upgrade over any existing file (or no file exists), not already imported for this download ID, contained in the grabbed release, not still being written/unpacked, sufficient free space, and valid readable archive — each rejection carrying a user-visible reason attached to the file.

- **Milestone**: M1
- **Source**: SA §5.2 (import specifications incl. MatchesGrabSpecification, NotUnpackingSpecification, FreeSpaceSpecification); SA §8 Import bullet 1; MFS §4 (CRC/ file-condition verification).
- **Notes**: Same spec pattern as the release decision engine (different AREA) — reuse the shape, not necessarily the code. Upgrade comparison uses the format-profile order from the quality area; at M1 with a trivial profile it degrades to "no file exists yet".

#### Scenario: All specs run and each yields a reason

- **WHEN** a candidate file is evaluated
- **THEN** the mapped-to-issue, archive-valid, free-space-with-margin, junk/sample-filter, and upgrade-allowed-vs-existing-file-per-format-profile specs all run (all-run, not short-circuited) and each contributes an accept/reject with a visible reason.

#### Scenario: Rejections persist as import_blocked with reasons

- **WHEN** one or more specs reject a candidate
- **THEN** the item persists as import_blocked with its reasons attached — never lost and never auto-deleted.

#### Scenario: All-pass imports

- **WHEN** every spec accepts a candidate
- **THEN** the file proceeds to import execution.

### Requirement: FRG-PP-006 — Archive validity verification

Before accepting a file, the import pipeline SHALL verify archive integrity — a cbz opens as a valid zip and contains at least one image entry; cbr/cb7 pass the equivalent container check — and SHALL route corrupt archives to failed-download handling rather than importing them.

- **Milestone**: M1
- **Source**: SA §5.1 ("a cbz is a zip: verify archive opens and contains images" — the ffprobe analogue); MFS §4 (CRC check, ComicTagger corrupt-archive detection).
- **Notes**: This is the comic replacement for Sonarr's media-stream specs. Password-protected archives count as invalid here (pairs with the failed/blocklist requirement).

#### Scenario: cbz validated via shared utility

- **WHEN** a cbz is verified through the shared security/archives.py utility
- **THEN** it is accepted only if it opens as a valid zip containing at least one image entry, and rejected otherwise.

#### Scenario: cbr checked by listing only in M1

- **WHEN** a cbr is verified
- **THEN** it passes on RAR magic via a listing-only container check, with no extraction performed in M1.

#### Scenario: Corrupt/password archive fails to blocklist and re-search

- **WHEN** an archive is corrupt or password-protected
- **THEN** it routes into the failed pipeline, which blocklists the release and triggers a re-search, rather than importing the file.

### Requirement: FRG-PP-007 — Safe file operations

Import execution SHALL place files by move (default for usenet/DDL), copy, or hardlink-then-fallback-to-copy per configuration and client capability, with automatic cross-device fallback (copy+verify+delete when rename crosses filesystems) and a free-space check on the destination volume before any transfer begins.

- **Milestone**: M1
- **Source**: SA §5.3 (move vs copy vs hardlink, CanMoveFiles); MFS §4 Moving/renaming (FILE_OPTS incl. cross-device fallback, free-space guard); SA §8 Import bullet 2.
- **Notes**: Softlinks deliberately dropped (Mylar offers them but they disable tagging and add fragility); hardlink retained for same-volume dedupe. Never delete the source until the destination is verified (size/checksum).

#### Scenario: Same-device rename, cross-device copy-verify-delete

- **WHEN** the destination is on the same device as the source
- **THEN** the file is placed by rename; when it crosses a filesystem boundary the pipeline instead copies to a temp path, fsyncs, verifies size, atomically renames into place, and only then deletes the source.

#### Scenario: Free-space check with margin aborts before copy

- **WHEN** the destination volume lacks free space plus the configured margin
- **THEN** the transfer aborts before any copy begins, leaving the source intact.

#### Scenario: No partial files at final paths

- **WHEN** a transfer is interrupted before verification completes
- **THEN** no partial file remains at the final destination path and the source is retained (source removed only after the destination is verified).

### Requirement: FRG-PP-008 — Remote path mapping

The system SHALL support per-download-client remote-path mappings that translate the client's reported completed paths into locally valid paths before import, and SHALL surface an unreachable/foreign output path as an import-blocked condition naming the mapping as the likely fix.

- **Milestone**: M1
- **Source**: SA §4.2 (RemotePathMappings on SAB history Storage), §4.5 (foreign-OS path ⇒ warn); MFS §4 (cdh_mapping.CDH_MAP).
- **Notes**: M1-relevant because the deployment target is Docker where SAB and foragerr see different container paths for the same volume.

#### Scenario: Mapped path translated before import

- **WHEN** a client-reported completed path matches an entry in the change-5 remote-path mapping table
- **THEN** it is translated to the locally valid path before import and the file imports.

#### Scenario: Unmapped path blocks, never guessed

- **WHEN** a completed path has no matching mapping and is not locally reachable
- **THEN** the item becomes import_blocked with a reason naming remote-path mapping as the likely fix, and no local path is guessed.

### Requirement: FRG-PP-009 — Token-based renaming engine

File naming SHALL be driven by a configurable token template supporting at minimum {Series Title}, {Series CleanTitle}, {Volume}, {Year}, zero-padded decimal-safe {Issue:000}, {Issue Title}, {Classification} (Annual/Special rendering), {Booktype}, {Release Group}, and {IssueId} tokens — with token-case controlling output case, illegal-character replacement policy, byte-aware truncation to path-length limits, and a switch to disable renaming (keep original filename) entirely.

- **Milestone**: M1
- **Source**: SA §5.4 (FileNameBuilder token system, comic token list); MFS §4 Moving/renaming (FILE_FORMAT tokens, zero-level padding, lowercase/space options); MFP §2.16 (round-trip contract: renamed output must re-parse).
- **Notes**: Round-trip requirement: every rename template output in the test matrix must re-parse via the IMP parser to the same issue identity (this closes Mylar's four-way normalization divergence). Issue rendering uses the single ordering/normalization implementation from IMP.

#### Scenario: Tokens, padding, and case render as specified

- **WHEN** a name is rendered from a token template using {Series Title}, {Issue Number:000}, {Year}, {Release Group}, {Classification}, and [__{IssueId}__]
- **THEN** padding specifiers, illegal-character replacement, byte-aware truncation, and case control are all applied to the output; and a decimal issue such as `15.5` renders decimal-safe under `{Issue:000}`.

#### Scenario: Optional groups dropped when empty

- **WHEN** an optional-group segment references tokens that are empty for the issue
- **THEN** that group is dropped entirely from the rendered name.

#### Scenario: Round-trip contract holds over the corpus

- **WHEN** any rendered name is re-parsed by the single change-2 parser (property-tested over the corpus identities)
- **THEN** it yields the same series matching key and issue identity (equal ordering key) as the source record.

#### Scenario: Rename can be disabled

- **WHEN** renaming is disabled
- **THEN** the file imports under its original filename.

### Requirement: FRG-PP-010 — Folder templates and folder lifecycle

Series folder paths SHALL be built from a configurable folder template (at minimum {Series Title}, {Year}, {Volume}, {Publisher}, {Booktype} tokens), created automatically on first import, and a move-mode import SHALL delete the emptied source download folder only when nothing but junk remains in it.

- **Milestone**: M1
- **Source**: SA §5.3 (auto-created folders, ShouldDeleteFolder); MFS §4 (FOLDER_FORMAT tokens, booktype-in-folder only for non-print); SA §8 Import bullet 3.
- **Notes**: Same token engine as file renaming — one template implementation. Per-series folder overrides/locks (Mylar SER surface) are out of PP scope.

#### Scenario: Folder built via safe_join

- **WHEN** a series folder path is built from the folder template on first import
- **THEN** the directories are created via safe_join and the templated folder appears under the library root.

#### Scenario: Emptied source dirs removed up to the root

- **WHEN** a move-mode import empties a source download directory
- **THEN** the emptied directories are removed up to (but not including) the root/staging root, while a directory still holding a non-junk sibling file survives.

#### Scenario: Upgrade quarantines the replaced file

- **WHEN** an import replaces an existing file as an upgrade
- **THEN** the issue_files row is swapped to the new file and the replaced file is moved to `<config>/quarantine/<date>/` — never deleted (M1 stand-in for the M2 recycle bin).

### Requirement: FRG-PP-011 — Import history events

The system SHALL record a history event for every pipeline outcome — grabbed, imported, download-failed, file-deleted, file-renamed, upgrade-replaced — each carrying the series/issue, source title, download ID where applicable, and a per-event data payload, queryable per issue and globally.

- **Milestone**: M1
- **Source**: SA §4.3 (grab history rows), §7.3 (HistoryResource eventType vocabulary); SA §8 Downloading bullet 2.
- **Notes**: Grabbed events belong to the download AREA at write time but share this one history store; listed here because import events and the ID join are PP's contract. History backs already-imported and blocklist decisions.

#### Scenario: Events written in the same transaction

- **WHEN** a pipeline outcome occurs (grabbed / imported / import_failed / import_blocked / upgrade-replaced)
- **THEN** an import_history row is written in the same transaction as the outcome, keyed by download_id, carrying the issue, event type, reasons JSON, and provenance.

#### Scenario: Ordered events queryable and joined by download ID

- **WHEN** one download progresses grab → import → later upgrade
- **THEN** the resulting import_history rows are ordered, joined by download_id, and queryable both per issue and globally.

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

### Requirement: FRG-PP-014 — Duplicate constraint handling

When an incoming file targets an issue that already has a file and the release is not a profile-driven upgrade, the system SHALL resolve the duplicate by a configurable constraint — preferred format or larger file size (default) — with explicit fixed-release markers (`(f1)`/`(f2)`-style) always winning, and SHALL optionally move the losing file to a duplicate-dump folder (dated subfolders supported) instead of deleting it.

- **Milestone**: M2
- **Source**: MFS §4 Duplicate handling (`duplicate_filecheck`, DUPECONSTRAINT, DDUMP); SA §5.2 (UpgradeSpecification interplay).
- **Notes**: Ordering with the profile system: profile-order upgrade decision first (Sonarr semantics); the dupe constraint only arbitrates same-rung ties — a deliberate merge of Mylar's standalone dupe logic into the Sonarr decision shape.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Fixture pairs (cbz-vs-cbr under each constraint, smaller-fixed-release-vs- larger-plain) resolve as configured, with the loser landing in the dump folder when enabled.

### Requirement: FRG-PP-016 — Manual import resolution

The system SHALL provide a manual import view listing candidate files (from an import-blocked download or an arbitrary folder) with their would-be decisions and rejection reasons, allowing the user to override series, issue, and format per file and then execute those files through the shared import pipeline.

- **Milestone**: M2
- **Source**: SA §5.5 (ManualImportService — "the escape hatch for every mapping failure"), §4.5 (ImportBlocked → ManualInteractionRequiredEvent); MFS §4 (manual PP of arbitrary folder).
- **Notes**: This is the resolution path the M1 import-blocked state points at; at M1 the state is visible but resolution may be limited to retry/remove. Shares the staging/override UI patterns with IMP library-import review — build once.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An import-blocked fixture download is fully resolved to imported via manual overrides, and an arbitrary folder of unmatched files imports the same way.

### Requirement: FRG-PP-017 — ComicInfo.xml tagging on import

When tagging is enabled, the import pipeline SHALL write ComicInfo.xml metadata (series, issue number, title, volume, cover date, publisher, ComicVine issue ID, story-arc fields where known) into cbz archives in-process during import, sourced from the matched ComicVine issue record, without shelling out to an external ComicTagger installation.

- **Milestone**: M2
- **Source**: MFS §4 Metadata tagging (cmtagmylar subprocess flow — the behavior to keep, the subprocess mechanism to drop); MFS §8 candidate PP requirements bullet 3.
- **Notes**: In-process (zip rewrite in Python) is stated design freedom — noted as the intended divergence from Mylar's ComicTagger subprocess; if a library dependency proves inadequate, falling back to an optional external tagger must be a config choice, not a requirement change. Metadata *content* comes from the META/ComicVine area. Tagging failures must not fail the import (file lands untagged + warning event).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An imported fixture cbz contains a schema-valid ComicInfo.xml whose fields match the library issue record; import succeeds with tagging disabled and the archive is untouched.

### Requirement: FRG-PP-018 — CBR-to-CBZ conversion and library-wide retagging

The system SHALL optionally convert CBR archives to CBZ at import time (verifying the converted archive before discarding the original), and SHALL support on-demand retag/convert operations per issue, per series, and library-wide, throttled to respect ComicVine API rate limits.

- **Milestone**: B
- **Source**: MFS §4 Metadata tagging (CBR→CBZ, CBR2CBZ_ONLY, group_metatag with CV batch-limit protection); MFS capability map META/PP.
- **Notes**: Depends on the tagging requirement above. Conversion is where the cbz-preferred format profile (quality AREA) becomes actionable for existing files. Rar extraction needs an unrar capability in the Docker image — deployment note.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A cbr fixture imports as a verified cbz with the original removed only after verification; a mock library-wide retag of 3 series observes the configured rate throttle and updates every archive.

### Requirement: FRG-PP-019 — Permissions and ownership enforcement

The system SHALL optionally apply configured file/directory modes and owner/group to everything it creates or moves into the library, failing soft (import succeeds, warning event emitted) when the platform or privileges do not permit the change.

- **Milestone**: B
- **Source**: MFS §4 Moving/renaming (CHMOD_FILE/DIR, CHOWNER/CHGROUP); MFS §7 Perms section.
- **Notes**: Largely superseded by linuxserver.io PUID/PGID container conventions (the stated deployment target) — backlogged; revisit only if bare-metal deployment appears. Mylar's pre/extra/on-snatch shell script hooks are deliberately omitted entirely (single-user private tool; new attack surface per FRG-PROC-006 with no payoff) — recorded here so the omission is a decision, not an oversight.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With enforcement configured, imported files/folders carry the configured mode/owner in a privileged test environment; in an unprivileged environment the import still succeeds with a warning event.

