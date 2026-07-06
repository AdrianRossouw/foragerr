## Why

M2's core promise is "own your library": Adrian has an existing comic collection
(the real `/Volumes/comics` library) that foragerr cannot ingest today — series
must be added one at a time via Add Series, and files only enter the library via
the download pipeline or per-file manual import. This change delivers the
mass-import path: scan a root folder, propose ComicVine matches per series
folder, review/correct, and bulk-add series with their existing files imported
in place. It also lands the duplicate-constraint arbitration (FRG-PP-014) that
same-rung file collisions need once a library can contain pre-existing files.

## What Changes

- **Library scan walk (FRG-IMP-022)**: the shared archive walk gains junk
  skipping (AppleDouble/`@eaDir` dirs, `._` resource forks, dotfiles, zero-byte
  files, unpack-temp folders), and DB-vs-disk reconciliation (removing
  `issue_files` rows whose files vanished) is generalized from the per-series
  rescan to the root-folder scan.
- **Library-import staging and review (FRG-IMP-023)**: a scan-root command
  walks unmapped files, parses and groups them by normalized series name
  (`matching_key`), stages groups with per-group ComicVine match proposals and
  parse confidence, and supports mass import, per-group override, and re-check.
  Import executes through the SAME `import_candidate` pipeline (one
  `aggregate → decide → execute`), with `library_import_mode` (`in_place`
  default vs `move`) finally wired.
- **Library import UI (FRG-UI-015)**: a Library Import screen: pick a root
  folder, run the scan, review proposed matches per folder (confidence, poster,
  year, issue counts), confirm/correct via the existing lookup, then bulk-add —
  series created with existing files registered (`hasFile`) without downloads.
- **Duplicate constraint handling (FRG-PP-014)**: profile-order upgrades keep
  deciding first (Sonarr semantics); the new configurable constraint (preferred
  format or larger-size, default larger-size) arbitrates only same-rung ties;
  fixed-release markers (`(f1)`/`(f2)`) always win; the losing file optionally
  moves to a duplicate-dump folder (dated subfolders) instead of being deleted.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `imp`: FRG-IMP-022 (scan walk junk rules + reconciliation scope) and
  FRG-IMP-023 (staging/review mechanics) elaborated from baseline-acceptance
  placeholders to concrete scenarios.
- `ui`: FRG-UI-015 elaborated (screen flow, states, bulk-add behavior).
- `pp`: FRG-PP-014 elaborated (tie-only arbitration order, marker precedence,
  dump-folder mechanics vs recycle bin).

## Impact

- **Code**: `backend/src/foragerr/library/matching.py` (walk junk rules),
  `library/flows/` (new library-import flow + command; rescan reconciliation
  generalized), `importer/` (new `LibraryImportSource` following
  `ManualImportSource`'s shape; `UpgradeAllowedSpec` tie seam + dupe-constraint
  spec; dump-folder fileop), `config.py` + `api/config_resources.py` (PP-014
  settings; `library_import_mode` consumed at the `place_file` seam),
  new API endpoints (scan dispatch + staged-groups listing following the
  manual-import pattern), parser (fixed-release marker annotation),
  `frontend/src` (Library Import screen + nav + hooks).
- **DB**: new staging persistence for scan results (net-new table) — additive
  migration.
- **Security docs**: scan endpoints accept user-supplied paths → same
  `confine_under_roots` posture as manual import (FRG-SEC-004); no new listener
  or credential. `docs/security/` gets a delta note in-change.
- **Manual** (FRG-PROC-011): new user-manual section for Library Import;
  media-management settings section gains the duplicate-constraint fields.
- **Dependencies / SOUP**: none expected.

## Non-goals

- No ComicVine bulk auto-add without review (user always confirms matches).
- No metadata-only "watch folder" ingestion; scans are user-initiated.
- No change to quality/upgrade profiles (QUAL-003/004/005 stay parked in B).
- Trades/volume grouping remain M3.

## Approval

Covered by Adrian's standing FRG-PROC-009 grant of 2026-07-06 for all M2/M3
changes ("keep going with m2/m3 and all their related changes as you go");
recorded per the M1-style standing-grant model.
