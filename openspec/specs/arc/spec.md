# ARC — Story Arcs Specification

## Purpose

Baseline requirements for story arcs, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).

## Requirements

### Requirement: FRG-ARC-001 — Arc entity import by ComicVine arc ID

The system SHALL import a story arc by ComicVine arc ID (4045-), persisting arc metadata (name, publisher, year derived from first appearance, description, arc image) and one ordered member record per ComicVine issue in the arc, each carrying the ComicVine issue ID, its source volume ID, and a reading-order position.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §2 (addStoryArc, storyarcinfo); mylar-comicvine.md §1.6 (story-arc search, arclist id/order pairs).
- **Notes**: Arc member issue metadata comes via META's batched issue lookup (≤100 IDs/call) under the same rate limiter. Arc search-by-name reuses META's search with `search_type=story_arc`.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Importing a known arc ID creates the arc with the full ordered issue list and a cached arc image; re-importing the same ID does not duplicate.

### Requirement: FRG-ARC-002 — Arc-to-library linking by ComicVine ID

The system SHALL link each arc member to its library issue by ComicVine issue ID whenever the issue exists in the library, updating links automatically when series are added, refreshed, or removed, and SHALL represent members without a library issue as unlinked (with their source series/volume identity retained).

- **Milestone**: B
- **Source**: mylar-feature-surface.md §2 (ArcWatchlist matching); mylar-comicvine.md §1.1 (arc issues fetched by CV issue ID).
- **Notes**: Deliberate divergence: Mylar matches by DynamicComicName + issue number + date guard because its arc rows are name-based; foragerr's arc members carry CV issue IDs end-to-end, so fuzzy matching (and its wrong-volume guard) is unnecessary. D4: links, not copied status.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Importing an arc whose issues span one watched and one unwatched series links all watched-series members; subsequently adding the second series links the rest with no manual action.

### Requirement: FRG-ARC-003 — Arc progress

The system SHALL compute arc completion as owned/total derived from linked member issues' file presence, exposed on arc list and detail views, with unlinked members counting as not owned.

- **Milestone**: B
- **Source**: mylar-feature-surface.md capability map ARC (arc progress have/total); sonarr-architecture.md §8 (derived statistics pattern).
- **Notes**: Same derived-aggregation pattern as SER statistics (D1).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An arc with 12 members, 5 linked-with-file, reports 5/12; importing a file for a linked issue updates the count without any arc-side write.

### Requirement: FRG-ARC-004 — Wanting missing arc issues

The system SHALL provide an arc-level "want missing" action that sets the monitored flag on linked-but-unowned member issues (and their series where needed) so they enter the standard derived-wanted search pipeline, and SHALL NOT issue standalone searches outside the library model.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §2 (ReadGetWanted, arc rows swept by auto-search); sonarr-architecture.md §1.3, §8 (monitored as the single gate).
- **Notes**: Deliberate divergence from Mylar's standalone arc searches with synthetic `'S'+IssueArcID` IDs (D1/D4). Issues from series not in the library are handled by the next requirement, not by one-off search.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Invoking want-missing on a partially owned arc flips the relevant issue monitored flags; the issues appear in Wanted and are picked up by the normal search job; no arc-specific search records exist.

### Requirement: FRG-ARC-005 — Add missing series from arc

The system SHALL provide actions to add a single arc member's series, or all missing series in an arc, to the library via the standard add flow, defaulting to monitoring strategy "none" with only the arc member issues monitored.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §2 (addMissingSeriesFromArc) and capability map ARC; sonarr-architecture.md §1.2 (add flow chain).
- **Notes**: The monitor-none-except-arc-issues default is the Sonarr-shaped replacement for Mylar one-offs: the library stays the single source of truth without auto-wanting whole series the user only needs one issue from. Default is overridable at add time.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Bulk-adding missing series from an arc creates each series with only its arc issues monitored; the arc becomes fully linked; Wanted contains exactly the missing arc issues.

### Requirement: FRG-ARC-006 — Arc refresh reconciliation

The system SHALL support a manual arc refresh command that re-fetches the arc from ComicVine and reconciles membership and reading order by ComicVine issue ID — inserting new members, updating changed order/metadata, and removing members absent from the source — while never removing user-added manual members.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §2 (arcrefresh; no scheduled arc job); sonarr-architecture.md §1.2 (reconciliation pattern).
- **Notes**: Same reconciliation shape as META series refresh, applied to arcs. Matching Mylar, no scheduled arc refresh — manual/on-demand only (arcs change rarely); revisit if stale arcs prove annoying.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Refreshing an arc against a fixture with one added, one reordered, and one removed member applies exactly those changes; a manually added member survives.

### Requirement: FRG-ARC-007 — Reading-order editing and manual members

The system SHALL allow reordering arc members and adding manual members (library issues not returned by ComicVine for that arc), persisting a `manual` provenance flag on such members so refresh reconciliation preserves them and their positions.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §2 (manual issues, reading-order edits, webserve.py:4877,4985) and capability map ARC.
- **Notes**: Reading order is a dense integer sequence renumbered on edit; provenance flag mirrors META's heuristic/user provenance pattern.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Moving a member from position 8 to 2 persists across restart and refresh; a manually added issue appears at its assigned position after an arc refresh.

### Requirement: FRG-ARC-008 — CBL reading-list import

The system SHALL import a ComicRack CBL reading list as an arc via a two-step validate-then-confirm flow: parse the CBL, resolve each entry to ComicVine (reporting unresolved entries), preview the resulting arc with per-entry resolution status, and on confirmation create the arc with options to add missing series and monitor missing issues.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §2 (CBL two-step validate/process, CBL_IMPORT_ISSUESONLY/IGNOREARCHIVED) and capability map ARC.
- **Notes**: CBL files are untrusted XML from the internet — parse with a hardened parser (no entity expansion), security note required (FRG-PROC-006). Mylar's ISSUESONLY / IGNOREARCHIVED toggles become the preview's per-run options.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Importing a fixture CBL with 10 entries (8 resolvable) previews 8 resolved + 2 unresolved; confirming with "add missing series" creates the arc, the series, and the monitored issues.

### Requirement: FRG-ARC-009 — Arc directory materialization

The system SHALL optionally materialize an arc as a dedicated directory under a configured arc root, populated with copies or hardlinks (configurable, default copy) of owned member files named per an arc folder/file template including an optional reading-order filename prefix — without moving, renaming, or otherwise disturbing the canonical library files.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §2 (STORYARCDIR, ARC_FOLDERFORMAT, ARC_FILEOPS, READ2FILENAME) and capability map ARC.
- **Notes**: Symlinks dropped from Mylar's option set (poor Docker-volume/OPDS interaction); copy/hardlink only. `cvinfo` file writing excluded (see META exclusions). Idempotent re-materialization replaces Mylar's one-shot file-ops. Template tokens defined by the naming-engine area; arc supplies `$arc`, `$spanyears`, `$publisher` equivalents.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Materializing a half-owned arc produces a folder containing exactly the owned files, order-prefixed per the template; the canonical files' paths and mtimes are unchanged; re-materializing after acquiring another issue adds only the new file.

### Requirement: FRG-ARC-010 — Arcs in OPDS (boundary requirement)

The system SHALL expose each arc's owned member files as a reading-order-sorted browsable group through the catalog layer (OPDS AREA implements the feed; ARC provides the ordered projection).

- **Milestone**: B
- **Source**: mylar-feature-surface.md capability map ARC + OPDS; sonarr-architecture.md §8 (OPDS as read-only projection).
- **Notes**: Dedup hint for orchestrator: the feed itself belongs to the OPDS AREA; this requirement pins only that arcs expose the ordered projection, so iPad reading of an arc needs no directory materialization.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An arc with owned files is retrievable via an API/catalog projection listing files in reading order.

