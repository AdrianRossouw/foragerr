# ui — delta for m2-existing-library-import

## MODIFIED Requirements

### Requirement: FRG-UI-015 — Library import (existing files) flow

The UI SHALL provide a library-import flow that scans a chosen root folder for unmapped series folders, proposes ComicVine matches per folder, and lets the user confirm/correct matches before bulk-adding series with their existing files imported in place.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §5.5 (RootFolderService unmapped-folder enumeration feeding "import existing library" UI), §7.4 (AddSeries library import); mylar-feature-surface.md §IMP.
- **Notes**: Backend scanning/matching is IMP area. Mylar's importresults staging UI is the ancestor; Sonarr's folder-level flow is the shape to copy. The scan runs as a command (WS command-status invalidation drives progress, as the manual-import overlay does); match correction reuses the existing ComicVine lookup; bulk-add reuses the add-options pieces (root folder, format profile, monitor strategy) applied once for the whole batch with per-group opt-out.

#### Scenario: Scan and review proposed matches

- **WHEN** the user opens Library Import, picks a configured root folder, and starts a scan
- **THEN** a running state is visible until the scan command completes, then staged groups render — folder name, file count, parse confidence, and the proposed ComicVine match (poster, name, year, publisher) or an explicit no-match state — with nothing imported yet

#### Scenario: Correcting a match before import

- **WHEN** the user rejects a proposed match on a group and searches ComicVine inline
- **THEN** the group updates to the chosen volume and is marked user-confirmed; groups with no plausible match require this explicit choice before they can be selected for import

#### Scenario: Bulk-add applies batch options and shows per-group outcomes

- **WHEN** the user selects groups, sets batch add options (root folder is the scanned one; format profile, monitor strategy), and confirms the import
- **THEN** each selected group becomes a series whose existing files import through the shared pipeline — issues show `hasFile` without any download — and per-group success/blocked outcomes render (blocked reasons visible, consistent with the manual-import overlay's reasons presentation)

#### Scenario: Unconfigured and empty states are explicit

- **WHEN** no root folders are configured, or a scan finds nothing to import (fully-mapped library)
- **THEN** the screen says so explicitly (pointing at Settings for the former) — never a blank or misleading empty results area
