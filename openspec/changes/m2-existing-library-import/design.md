# Design — m2-existing-library-import

## Context

The importer already has everything but the mass path: a source-driven pipeline
(`ImportSource.gather → aggregate → decide → execute`, per-candidate SAVEPOINT),
three sources (`CompletedDownloadSource`, `RescanSource`, `ManualImportSource`),
a decision-spec set ending in `UpgradeAllowedSpec` (strict rank), ch2's staged
manual-import listing/execute with `confine_under_roots`, ch1's naming engine +
recycle bin, and a shared walk (`matching.iter_archive_files`) with NO junk
rules. `library_import_mode` exists in config + settings UI but is consumed
nowhere. Per-series rescan already reconciles vanished files
(`flows/rescan.py`); root scope does not. No staging table exists — the old
`scan_series` docstring explicitly deferred it to this change.

## Goals / Non-Goals

**Goals:** junk-aware shared walk; persisted, reviewable scan staging grouped by
`matching_key`; per-group CV match proposals with confidence; bulk-add through
the existing `add_series` + shared import pipeline; `library_import_mode`
wired; same-rung duplicate arbitration with markers + dump folder.

**Non-Goals:** watch-folder ingestion; auto-import without review; upgrade
profile changes; trade/volume grouping (M3); OPDS changes.

## Decisions

1. **Junk rules live in `iter_archive_files`** (`library/matching.py`) — one
   predicate module (`is_junk_dir` / `is_junk_file`) applied during the walk so
   rescan, manual import, and library import all inherit it. Zero-byte files
   are skipped at walk time (stat is already taken for size); the decision-time
   `JunkFilterSpec` size-floor stays as the second gate. Alternative (per-source
   filtering) rejected: three copies of the same rules.
2. **Staging is a real table** (`library_import_groups`): group key
   (`matching_key`), root_folder_id, folder path, file list (JSON), parse
   confidence, proposed/confirmed `cv_volume_id`, state
   (`proposed|confirmed|no_match|imported|skipped`), scanned_at. Persisted so
   review survives restarts (FRG-IMP-023 scenario). Additive migration.
   Re-scan replaces stale groups for that root atomically. Alternative
   (in-memory staging like manual import's listing) rejected: a 2000-file
   library scan is too expensive to redo per page load and the spec requires
   restart survival.
3. **Scan is a command** (`library-import-scan`, `workload_class="pp"`) but
   read-only w.r.t. files, so it does NOT take `IMPORT_FILE_MUTATION_GROUP`;
   it walks the root, reconciles vanished rows (write txn), parses folder+file
   names via the existing evidence layers, groups, proposes matches via ONE
   `search_series` call per group (rate-limited politeness; groups above a
   plausibility floor get the top candidate attached, below it `no_match`),
   and upserts staging rows. WS command-status invalidation drives the UI.
4. **Import executes as bulk `add_series` + `LibraryImportSource`**: per
   confirmed group — `add_series` (existing flow: CV fetch, path build,
   refresh chain) with `path_override` = the group's existing folder when
   in-place, then a `library-import` command (takes
   `IMPORT_FILE_MUTATION_GROUP`) whose source yields the group's files with
   the confirmed series pinned as overrides. Safety specs still run.
   `library_import_mode` is consumed at the placement seam: in `execute`,
   in-place candidates whose current path is already the computed destination
   (or under the series folder with rename disabled) register the row without
   `place_file`; `move` mode routes through `place_file`/rename as downloads
   do. The refresh chain's `scan-series` then attaches anything the import
   registered (idempotent — `AlreadyImportedSpec`/path-unique guard).
5. **PP-014 slots into the existing spec chain**: `UpgradeAllowedSpec` keeps
   strict `>` (upgrades) and keeps rejecting `<` (downgrades);a new
   `DuplicateConstraintSpec` evaluates ONLY the `==` tie, reading
   `duplicate_constraint` (`larger-size` default | `preferred-format`) and the
   parsed fix markers (parser gains an `(fN)` annotation on `ParseResult`).
   Loser disposal extends `execute`'s replaced-file branch: dump folder
   (dated subdir via the recycle-bin date/collision helpers, but a distinct
   unmarked root so `prune_recycle_bin` can never touch it) when
   `duplicate_dump_path` is set, else existing recycle/delete path. New config:
   `duplicate_constraint`, `duplicate_dump_path` (+ config resource + settings
   UI fields).
6. **API shape follows manual import**: `POST /api/v1/library-import/scan`
   (root_folder_id) → 201 CommandResource; `GET /api/v1/library-import`
   (groups for a root, paged envelope); `PATCH .../groups/{id}` (confirm/
   override/skip — override validated against CV like add); `POST
   /api/v1/library-import/execute` (group ids + batch add options) → 201
   CommandResource. Paths only ever come from configured root folders — user
   input is a root_folder_id, not a path, so no new path-confinement surface
   beyond the existing FRG-SEC-004 posture.
7. **UI**: new `screens/library-import/` + route + sidebar entry. Reuses
   `useRootFolders`/`useFormatProfiles`, the lookup (for correction),
   `ReasonsPopover` (blocked outcomes), command polling à la
   ManualImportOverlay. Query keys follow the source-keyed `manualImport`
   style.
8. **Import-cycle discipline** (known landmine): the new flow module lives in
   `library/flows/` (may import `importer`); NOTHING under `importer/` imports
   `library.flows`. The new source gets candidates' series ids injected by the
   flow, not by importing flow code.

## Risks / Trade-offs

- [One CV search per group on big libraries is slow] → politeness-gated and
  command-async by design; groups render as they stage? No — staging upserts
  once at scan end per group loop; acceptable because the UI polls the
  command. Cap: scan proposes matches only for the first N unconfirmed groups
  per run (config default generous) and marks the rest `proposed=None` for
  lazy proposal on demand — logged, never silent.
- [Bulk add_series does a live CV get_volume per group] → inherent (add needs
  volume data); the execute command serializes them behind the rate gate;
  outcomes stream per group into staging state.
- [In-place under a foreign root: files live in root A but batch options say
  root B] → in-place pins the series to the scanned root (path_override);
  root selection for the batch only applies in `move` mode.
- [Marker parsing false positives (`(f1)` in a title)] → annotation only
  affects same-rung ties; title-plausibility guard in the parser rule; corpus
  rows pin behavior.
- [Staging table drift vs disk between scan and execute] → execute re-checks
  file existence per candidate (gather skips vanished) and `AlreadyImported`/
  unique-path constraints make repeats safe; re-check endpoint re-runs the
  scan for the root.

## Migration Plan

Additive migration (new table + two config fields). No data backfill. Rollback
= revert merge (table orphaned but harmless).

## Open Questions

None blocking; match-proposal cap default (Decision-risk 1) tuned during
implementation with the real `/Volumes/comics` fixture.
