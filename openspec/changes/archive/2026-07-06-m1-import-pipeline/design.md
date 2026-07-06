# Design: m1-import-pipeline

## Context

Builds on changes 1-5. Sonarr §5 (one import pipeline for download + rescan) is the
blueprint; mylar-filename-parsing §2.16/§5 pins the rename round-trip contract;
FRG-SEC-003/004 land here because this change is where untrusted archives first get
processed and where path construction becomes systematic. Drains change-5's
`import_pending` tracked downloads and completes FRG-DL-009/010 + FRG-SER-010.

## Goals / Non-Goals

**Goals:** completed downloads and rescans land as correctly named `issue_files`
rows through one pipeline, with visible reasons for anything blocked; renamed output
re-parses to the same identity; hostile archives cannot escape or exhaust.

**Non-Goals:** rename preview (M2), recycle bin (M2 — M1 uses a quarantine dir),
manual import (M2), ComicInfo tagging (M2), library-import staging (M2),
permissions (B).

## Decisions

1. **Pipeline shape** (`importer/pipeline.py`, FRG-PP-001): pure-ish stages —
   `gather(source) -> ImportCandidate[]` → `aggregate(candidate) -> Evidence` →
   `decide(evidence, ctx) -> ImportDecision(approved | blocked(reasons))` →
   `execute(approved) -> ImportedFile`. Two sources in M1: `CompletedDownloadSource`
   (tracked_downloads in import_pending) and `RescanSource` (series path walk).
   Same stages, same spec classes, same history events — the source is data, not a
   fork (mirrors the change-4 decision-engine pattern).

2. **Evidence aggregation** (FRG-PP-004): per candidate, parse (single parser) each
   evidence layer — file name, parent folder name (folder mode), client item title,
   grab-record parsed release — and merge by source-confidence order
   (grab record > embedded `[__issueid__]` tag > file name > folder > client
   title); each resolved field records its source for diagnostics. Issue-id tag
   short-circuits to a direct issue lookup (the DDL handshake).

3. **Decision specs** (FRG-PP-005): ordered, all-run, reasons visible (same
   contract as SRCH): mapped-to-series-and-issue; archive-valid (FRG-PP-006);
   free-space-with-margin; junk/sample filter (size floor, extension); upgrade
   check vs existing file (profile rung; equal-or-worse → blocked as
   not-an-upgrade unless no file exists). Outcome recorded on the tracked download
   / rescan report; `import_blocked` items persist with reasons (FRG-DL-009's
   blocked-not-lost guarantee).

4. **Archive verification** (FRG-PP-006 + SEC-003, `security/archives.py`): one
   shared utility used by PP now and OPDS/DDL later — `inspect_archive(path,
   limits) -> ArchiveReport` (stdlib zipfile; rarfile only for magic/entry listing,
   no extraction in M1): validates magic vs extension, member count cap, per-member
   + total decompressed-size caps, nesting depth 0 (no archive-in-archive for M1),
   rejects member names that are absolute / contain `..` / path separators
   escaping, symlink entries; ≥1 image entry for cbz/cbr. Hostile corpus committed
   as fixtures (bomb, nested bomb, slip names, symlink, huge-member,
   password-protected). Password/corrupt → failed pipeline → blocklist + re-search
   (change-5 loop).

5. **safe_join** (SEC-004, `security/paths.py`): `safe_join(root, *parts)` —
   normalize, reject absolute/parent traversal/reserved names, verify realpath
   containment under root; the ONLY way pipeline/renamer construct destination
   paths; property-tested with traversal corpus. Change-3's `safe_path_component`
   moves here (one module owns path safety).

6. **Safe file ops** (FRG-PP-007, `importer/fileops.py`): same-device rename else
   copy-to-temp + fsync + verify-size + atomic rename + delete-source; free-space
   check (size + configurable margin) before any copy; never leave partials at
   final paths (temp names under the destination dir, cleaned on failure).

7. **Renaming engine** (FRG-PP-009/010, `importer/renamer.py`): token template
   engine (fields from the issue/series/parse result; padding specifiers
   `{Issue Number:000}`; optional-group syntax `[...]` dropped when empty; token
   case control). M1 default file template
   `{Series Title} {Issue Number:000} ({Year}) [__{IssueId}__]` and folder template
   = change-3's fixed shape (now rendered by this engine — SER-008 template
   ownership transfers here). **Round-trip contract**: property test renders every
   corpus identity through the default + variant templates and asserts
   `parse(rendered)` recovers the same series matching key + issue identity
   (ordering key equal) — the FRG-IMP round-trip promise, now enforced end-to-end.
   Folder lifecycle: create dirs via safe_join; after moves, remove emptied
   source dirs up to (not including) the root folder / staging root.

8. **Upgrade handling without recycle bin (M1)**: replaced files move to
   `<config>/quarantine/<date>/` via safe file ops (never deleted); `issue_files`
   row swapped in the same write_session; quarantine pruning is a housekeeping
   setting. Documented as the M1 stand-in for FRG-PP-013 (M2).

9. **Completed-download handling** (FRG-DL-009/010 + FRG-PP-002/003): the ~1-min
   `ProcessImportsCommand` (pp pool) drains import_pending: reconcile by download
   ID (grab_history), remote-path-map, verify, pipeline; success → issue_files row
   + tracked_download `imported` + import history event + client
   `mark_imported`/remove per FRG-DL-010 gating (only-after-import, only-if-
   enabled); failure → `import_blocked` with reasons (retryable after user action;
   re-processed when the file/evidence changes). Rescan (FRG-SER-010):
   `RescanSeriesCommand` walks the series path (bounded depth, extension filter
   from the shared list), skips files already tracked, pipelines the rest;
   unmatched/blocked recorded on a per-series rescan report.

10. **History** (FRG-PP-011): `import_history` table (download_id join key,
    issue_id, event grabbed/imported/import_failed/import_blocked, reasons JSON,
    timestamps, source provenance) written inside the same transactions as the
    state changes; queryable by series/issue (API endpoint is M2; table feeds it).

## Risks / Trade-offs

- [Round-trip contract may surface parser gaps] → that is its purpose; failures
  add corpus rows (additive policy) and fix template or parser — never weaken the
  assertion.
- [rarfile dependency for CBR] → listing/magic only (unrar binary not required for
  M1 validation depth); documented; CBR contents unverified beyond magic + entry
  names when unrar absent — recorded as accepted M1 residual in the risk register.
- [Quarantine instead of recycle bin] → explicit M1 stand-in, documented; M2
  replaces with FRG-PP-013 without schema change (quarantine path recorded on the
  history event).
- [Rescan on network mounts may be slow] → bounded walk + per-series scope in M1;
  NFR-002 throughput acceptance is M2.

## Migration Plan

One forward migration: import_history, remote-path-mapping reuse (created in
change 5), quarantine bookkeeping fields. Rollback = don't merge.

## Open Questions

None blocking.
