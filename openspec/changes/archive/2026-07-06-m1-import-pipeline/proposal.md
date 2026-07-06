# Change: m1-import-pipeline — the shared import pipeline

## Why

Phase 3 change 6 of 7 (approved plan, 2026-07-04). Changes 4-5 grab and download;
this change lands files in the library: the single shared import pipeline (evidence
aggregation → decisions → execution) that serves completed-download handling AND
per-series rescan, the token renaming engine with its round-trip contract, and the
archive/path safety layer (FRG-SEC-003/004). It also completes the three
requirements deliberately parked earlier: FRG-DL-009/010 (completed handling +
post-import cleanup) and FRG-SER-010 (rescan routing unmatched files).

## What Changes

Implements 16 approved baseline requirements (no new IDs; scenario elaboration only):

- **Pipeline core (FRG-PP-001..005)** — one pipeline for all sources (download
  import, series rescan; manual import is M2 but the seam exists); completed-
  download handling state machine draining change-5's `import_pending` items on the
  ~1-min loop; grab reconciliation by download ID with parser fallback; evidence
  aggregation across file name / folder name / client title / grab record in
  source-confidence order (all via the single change-2 parser); ordered import
  decision specifications with visible reasons (matched-to-issue, archive-valid,
  free-space, not-a-sample/junk, upgrade-allowed vs existing file per profile) —
  unresolvable items become `import_blocked` with reasons, never lost, never
  auto-deleted.
- **Safety (FRG-PP-006, 007 · FRG-SEC-003, 004)** — archive validity verification
  (cbz = valid zip with ≥1 image entry; cbr = RAR magic; corrupt/password-protected
  → failed pipeline + blocklist); safe file operations (copy-verify-delete
  cross-device fallback, free-space guard with margin, no partial files visible at
  final paths); the single shared archive-limits utility (member count, per-member
  and total decompressed size caps, nesting depth) with a zip-slip/path-separator
  rejection corpus; the single `safe_join()` utility guaranteeing every constructed
  path stays under its root — adopted by OPDS/DDL/PP alike.
- **Renaming (FRG-PP-009, 010)** — token-based renaming engine
  (`{Series Title}`, `{Issue Number:000}`, `{Year}`, `{Release Group}`,
  `{Classification}`, `[__{IssueId}__]` …) with the round-trip contract: every
  rendered name re-parses to the same issue identity (property-tested against the
  corpus); folder templates + folder lifecycle (create on import, clean empty
  folders after moves); supersedes change-3's fixed path template.
- **Completion of parked requirements (FRG-DL-009, 010 · FRG-SER-010)** — completed
  downloads flow: verify → aggregate → decide → rename-into-library →
  `issue_files` row → tracked_download `imported` → client `mark_imported` +
  gated cleanup (remove-from-client only after successful import, only when the
  client setting allows); per-series rescan walks the series path, matches via the
  pipeline, routes unmatched files through the same decisions, records
  `import_blocked` leftovers for review.
- **History (FRG-PP-011)** — import history events (grabbed → imported /
  import_failed / import_blocked) joined by download ID, feeding the M2 history UI.

## Capabilities

### New Capabilities

None — all requirements exist in the approved baseline specs.

### Modified Capabilities

- `pp`: FRG-PP-001..011
- `dl`: FRG-DL-009, FRG-DL-010
- `ser`: FRG-SER-010
- `sec`: FRG-SEC-003, FRG-SEC-004

## Non-goals

- No rename preview endpoint (FRG-PP-012, M2), no recycle-bin upgrades/deletions
  (FRG-PP-013, M2 — M1 upgrades import alongside then swap the `issue_files` row;
  the replaced file moves to a quarantine dir under /config, not deletion), no
  duplicate-constraint handling (FRG-PP-014, M2), no manual import UI/endpoint
  (FRG-PP-016/FRG-API-015, M2), no ComicInfo.xml tagging (FRG-PP-017, M2), no
  permissions enforcement (FRG-PP-019, B).
- No library-import staging for existing libraries (FRG-IMP-023, M2) — rescan here
  serves already-added series only.

## Impact

- **New code**: `backend/src/foragerr/importer/` (pipeline, evidence, decisions,
  renamer, safe-ops), `security/archives.py` + `security/paths.py` shared
  utilities; migration for import_history + quarantine bookkeeping.
- **Security**: archive processing of untrusted downloads is the biggest new
  attack surface — hostile corpora (zip bombs, nested bombs, zip-slip names,
  symlink members, oversized members) committed; risk rows RISK-005/008/010
  (bombs/extraction), RISK-019/029 (path confinement) updated (FRG-PROC-006).
- **Registry**: on merge, the 16 rows flip `approved → implemented`.

## Approval

- **Approver:** Adrian
- **Date:** 2026-07-04
- **Decision:** Approved under the standing grant of 2026-07-04 covering changes
  3-7. Implementation may begin, scoped to the 16 requirements listed above.
