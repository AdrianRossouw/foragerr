# pp Spec Delta

## ADDED Requirements


### Requirement: FRG-PP-001 — Single shared import pipeline

Completed-download import, existing-library scan import, and manual import SHALL execute one shared import pipeline (evidence aggregation → import decisions → import execution), differing only in input source and a new-download flag — with no per-path forks of decision or file-op logic.

- **Milestone**: M1
- **Source**: SA §5.5 ("library import and download import share one pipeline — major simplification worth copying"); SA §8 Import/files bullet 1.
- **Notes**: This is the structural keystone of the AREA; every following requirement hangs off it. Deliberate divergence from Mylar's four separately-coded intake paths (MFS §4).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Pipeline tests drive the same entry point with a completed-download fixture, a library-rescan fixture, and a manual-import fixture, and a code audit shows a single decision/execution implementation.

### Requirement: FRG-PP-002 — Completed-download handling state machine

The system SHALL poll download clients (SABnzbd, built-in DDL) on a ~1-minute tracking loop, match items to grab history, and maintain a per-download state machine — downloading → import pending → importing → imported, with failed-pending → failed and import-blocked (manual interaction required) branches — that backs the visible queue, with no external client-side completion scripts required.

- **Milestone**: M1
- **Source**: SA §4.4–4.5 (DownloadMonitoringService, CompletedDownloadService, TrackedDownload states); MFS §4 pickup path 2 (CDH); SA §8 Downloading bullets 2–3.
- **Notes**: Deliberate divergence: Mylar's ComicRN.py external-script path and watched-folder monitor are dropped — CDH polling is the only automatic intake (plus manual import). Post-import removal from the client is gated by a per-client remove-completed flag (SA §4.5). Check (fast) vs process (slow) separation is a design hint, not a requirement.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An end-to-end test (mock SAB) drives one download through grab → downloading → imported with queue states observable at each step, and an unresolvable download lands in import-blocked with a user-visible message instead of failing silently.

### Requirement: FRG-PP-003 — Grab reconciliation by download ID

Every grab SHALL record a history row keyed by the download-client ID, and completed downloads SHALL be reconciled to their grabbed issues primarily by that ID, falling back to parsing the download title/folder name (via the single IMP parser, including the `[__issueid__]` tag for DDL) only when no history match exists.

- **Milestone**: M1
- **Source**: SA §4.3 ("DownloadId is the join key for the entire rest of the pipeline"); MFS §4 snatch↔download handshake (nzblog analogue); SA §8 Downloading bullet 2.
- **Notes**: Replaces Mylar's name-normalized `nzblog` matching (AltNZBName fragility) with Sonarr's ID join; the parse fallback covers Mylar's `mode='outside'` case.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A completed item whose folder name is unparseable still imports correctly via its download-ID history match; a history-less folder falls back to parse-based matching or import-blocked.

### Requirement: FRG-PP-004 — Import evidence aggregation

For each candidate file, the import pipeline SHALL aggregate parse evidence from the file name, the containing folder name, the download-client item title, embedded archive metadata where read, and the grab record, selecting per-field values by a defined source-confidence order and recording which source supplied each field.

- **Milestone**: M1
- **Source**: SA §5.1 (AggregationService: file/folder/client-title evidence, grab record by DownloadId); MFP §5 (folder-vs-filename provenance); SA §8 Import bullet 1.
- **Notes**: All evidence parsing goes through the single IMP parser. Confidence signals from the parser (IMP structured-result requirement) are the aggregation inputs.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A fixture where the file name is junk but the folder name and grab record are good imports to the correct issue, and the decision trace shows per-field provenance.

### Requirement: FRG-PP-005 — Import decision specifications with visible reasons

Each candidate file SHALL pass through an ordered set of accept/reject import specifications — at minimum: maps to a known series/issue, genuinely an upgrade over any existing file (or no file exists), not already imported for this download ID, contained in the grabbed release, not still being written/unpacked, sufficient free space, and valid readable archive — each rejection carrying a user-visible reason attached to the file.

- **Milestone**: M1
- **Source**: SA §5.2 (import specifications incl. MatchesGrabSpecification, NotUnpackingSpecification, FreeSpaceSpecification); SA §8 Import bullet 1; MFS §4 (CRC/ file-condition verification).
- **Notes**: Same spec pattern as the release decision engine (different AREA) — reuse the shape, not necessarily the code. Upgrade comparison uses the format-profile order from the quality area; at M1 with a trivial profile it degrades to "no file exists yet".

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** One fixture per specification produces the expected rejection with its reason string surfaced through the manual-import listing; an all-pass fixture imports.

### Requirement: FRG-PP-006 — Archive validity verification

Before accepting a file, the import pipeline SHALL verify archive integrity — a cbz opens as a valid zip and contains at least one image entry; cbr/cb7 pass the equivalent container check — and SHALL route corrupt archives to failed-download handling rather than importing them.

- **Milestone**: M1
- **Source**: SA §5.1 ("a cbz is a zip: verify archive opens and contains images" — the ffprobe analogue); MFS §4 (CRC check, ComicTagger corrupt-archive detection).
- **Notes**: This is the comic replacement for Sonarr's media-stream specs. Password-protected archives count as invalid here (pairs with the failed/blocklist requirement).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A truncated cbz and a zip-with-no-images are both rejected with distinct reasons and (for download-sourced files) trigger the failed path; a valid fixture passes.

### Requirement: FRG-PP-007 — Safe file operations

Import execution SHALL place files by move (default for usenet/DDL), copy, or hardlink-then-fallback-to-copy per configuration and client capability, with automatic cross-device fallback (copy+verify+delete when rename crosses filesystems) and a free-space check on the destination volume before any transfer begins.

- **Milestone**: M1
- **Source**: SA §5.3 (move vs copy vs hardlink, CanMoveFiles); MFS §4 Moving/renaming (FILE_OPTS incl. cross-device fallback, free-space guard); SA §8 Import bullet 2.
- **Notes**: Softlinks deliberately dropped (Mylar offers them but they disable tagging and add fragility); hardlink retained for same-volume dedupe. Never delete the source until the destination is verified (size/checksum).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Move across a filesystem boundary (tmpfs fixture) completes via the fallback with source removed only after a verified copy; an insufficient-space destination aborts cleanly before transfer with the source intact.

### Requirement: FRG-PP-008 — Remote path mapping

The system SHALL support per-download-client remote-path mappings that translate the client's reported completed paths into locally valid paths before import, and SHALL surface an unreachable/foreign output path as an import-blocked condition naming the mapping as the likely fix.

- **Milestone**: M1
- **Source**: SA §4.2 (RemotePathMappings on SAB history Storage), §4.5 (foreign-OS path ⇒ warn); MFS §4 (cdh_mapping.CDH_MAP).
- **Notes**: M1-relevant because the deployment target is Docker where SAB and foragerr see different container paths for the same volume.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With SAB reporting `/downloads/complete/x` mapped to a local mount, import succeeds; with no mapping and a nonexistent path, the queue item shows a "check remote path mapping" style warning instead of a crash.

### Requirement: FRG-PP-009 — Token-based renaming engine

File naming SHALL be driven by a configurable token template supporting at minimum {Series Title}, {Series CleanTitle}, {Volume}, {Year}, zero-padded decimal-safe {Issue:000}, {Issue Title}, {Classification} (Annual/Special rendering), {Booktype}, {Release Group}, and {IssueId} tokens — with token-case controlling output case, illegal-character replacement policy, byte-aware truncation to path-length limits, and a switch to disable renaming (keep original filename) entirely.

- **Milestone**: M1
- **Source**: SA §5.4 (FileNameBuilder token system, comic token list); MFS §4 Moving/renaming (FILE_FORMAT tokens, zero-level padding, lowercase/space options); MFP §2.16 (round-trip contract: renamed output must re-parse).
- **Notes**: Round-trip requirement: every rename template output in the test matrix must re-parse via the IMP parser to the same issue identity (this closes Mylar's four-way normalization divergence). Issue rendering uses the single ordering/normalization implementation from IMP.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A template test matrix covers each token (including a decimal issue `15.5` padded as `015.5`, an annual rendered per template, and a 300-char title truncated safely); disabling rename imports with the original name.

### Requirement: FRG-PP-010 — Folder templates and folder lifecycle

Series folder paths SHALL be built from a configurable folder template (at minimum {Series Title}, {Year}, {Volume}, {Publisher}, {Booktype} tokens), created automatically on first import, and a move-mode import SHALL delete the emptied source download folder only when nothing but junk remains in it.

- **Milestone**: M1
- **Source**: SA §5.3 (auto-created folders, ShouldDeleteFolder); MFS §4 (FOLDER_FORMAT tokens, booktype-in-folder only for non-print); SA §8 Import bullet 3.
- **Notes**: Same token engine as file renaming — one template implementation. Per-series folder overrides/locks (Mylar SER surface) are out of PP scope.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Importing into a fresh root creates the templated series folder; the source folder disappears after a move-mode import but survives when a non-junk sibling file is present.

### Requirement: FRG-PP-011 — Import history events

The system SHALL record a history event for every pipeline outcome — grabbed, imported, download-failed, file-deleted, file-renamed, upgrade-replaced — each carrying the series/issue, source title, download ID where applicable, and a per-event data payload, queryable per issue and globally.

- **Milestone**: M1
- **Source**: SA §4.3 (grab history rows), §7.3 (HistoryResource eventType vocabulary); SA §8 Downloading bullet 2.
- **Notes**: Grabbed events belong to the download AREA at write time but share this one history store; listed here because import events and the ID join are PP's contract. History backs already-imported and blocklist decisions.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Driving one download through grab → import → later upgrade produces the expected ordered event rows joined by download ID, visible via the history API.

### Requirement: FRG-PP-012 — Rename preview before execution

The system SHALL compute and return existing-path → new-path rename previews for any series or file selection under the current templates without touching disk, and SHALL execute renames only as an explicit second step that emits per-file rename events.

- **Milestone**: M2
- **Source**: SA §5.4 (RenameEpisodeFileService preview/execute split); SA §8 Import bullet 3 ("previewable before execution").
- **Notes**: Applies to bulk re-organization after template changes, not the initial import path (which names files directly). Same builder code as import naming.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Preview on a fixture series returns correct diffs with zero filesystem changes; executing then performs exactly the previewed operations.

### Requirement: FRG-PP-013 — Upgrades and deletions via recycle bin

When an import replaces an existing file (upgrade) or a library file is deleted through the application, the displaced file SHALL be moved to a configured recycle-bin location (with collision-safe naming and scheduled cleanup) before the replacement lands, deleting permanently only when no recycle bin is configured.

- **Milestone**: M2
- **Source**: SA §5.3 (UpgradeMediaFileService, RecycleBinProvider), §6.1 (CleanRecycleBin 24h); SA §8 Import bullet 2.
- **Notes**: M2 because real upgrades arrive with format profiles/cutoffs (quality AREA); the import-execution seam should be built recycle-bin-shaped at M1 (permanent delete behind the same interface).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An upgrade import with a recycle bin configured leaves the old file retrievable in the bin and the new file in place; with no bin configured the old file is gone and the event history records the replacement.

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

- **Milestone**: M3
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
