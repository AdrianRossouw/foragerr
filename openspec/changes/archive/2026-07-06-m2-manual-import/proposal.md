# Change: m2-manual-import — resolve blocked imports by hand, tag what lands

## Why

M2 change 2 of 6 (decomposition approved under the 2026-07-06 standing grant). M1's
blocked-not-lost guarantee parks anything the pipeline cannot resolve as
`import_blocked` with reasons — but the only remedies today are "fix the evidence
and wait" or remove the item. Manual import closes the loop: see each candidate
file's would-be decision, override series/issue/format per file, and push it
through the same shared pipeline. Alongside it land the two metadata halves that
make matching sticky: reading embedded ComicInfo.xml/ComicVine IDs during import
(evidence in), and writing ComicInfo.xml into cbz archives at import time when
enabled (metadata out) — the read side directly strengthens manual import's
suggestions.

## What Changes

Implements 5 approved baseline requirements (no new IDs; scenario elaboration
only):

- **FRG-PP-016 — Manual import resolution.** A manual-import view over candidate
  files (from an import-blocked download OR an arbitrary folder) showing each
  file's would-be decision and rejection reasons via the real decision specs;
  per-file series/issue/format overrides; execution through `import_candidate` —
  the same pipeline, evidence layer, history events, and safety rails as
  automatic import (no parallel code path).
- **FRG-API-015 — Manual import endpoint.** List candidates under a path (or for
  a blocked download) with decisions/reasons; accept corrected mappings for
  execution. Same envelope/error conventions as the rest of the API.
- **FRG-UI-014 — Manual import overlay.** Reachable from ImportBlocked queue rows
  and from a path picker; per-file override controls; Sonarr's interactive-import
  overlay is the design-school reference.
- **FRG-IMP-024 — Embedded metadata read during import.** `inspect`-time read of
  ComicInfo.xml (and embedded ComicVine issue ids) from archives, preferred as
  evidence over filename parses when verified — slotting into the change-6
  evidence aggregation as a new source-confidence layer (bounded by the shared
  `inspect_archive` limits; no extraction).
- **FRG-PP-017 — ComicInfo.xml tagging on import.** When enabled (off by
  default), write ComicInfo.xml into cbz archives in-process during import from
  the matched ComicVine record — no external ComicTagger. Archive rewrite is new
  attack surface: it MUST route through the shared archive-safety layer
  (FRG-SEC-003) and never rewrite in place (temp + atomic replace via the
  change-6 fileops discipline).

## Capabilities

### Modified Capabilities

- `pp`: FRG-PP-016, FRG-PP-017
- `api`: FRG-API-015
- `ui`: FRG-UI-014
- `imp`: FRG-IMP-024

## Non-goals

- No existing-library import staging/review (change 3 — manual import here serves
  blocked downloads and ad-hoc folders; the bulk existing-collection flow with
  its in-place default is change 3's).
- No tagging of formats other than cbz (cbr/cb7 are read-only containers here;
  read-side IMP-024 still applies to them via listing where safe).
- No re-tagging library sweep (tag-on-import only; a bulk retag job is backlog).
- No history UI (change 4).

## Impact

- **Code**: `importer/` (evidence layer + manual candidate source + overrides),
  new `metadata/comicinfo.py` (read+write), `api/manual_import.py`,
  `frontend/src/screens/queue/` overlay + path picker.
- **Security**: TWO new untrusted-input surfaces, both spec'd per FRG-PROC-006 in
  the same change: (1) ComicInfo.xml parsing from untrusted archives — MUST use
  the hardened defusedxml site (FRG-SEC-002 pattern) with size caps via
  `inspect_archive`; (2) in-process cbz rewrite (FRG-PP-017) — zip-slip-safe
  member copy, temp-file + atomic replace, never extraction to disk. Risk
  register rows RISK-010/024 get M2 dispositions at the gate; threat model COMP 7
  delta.
- **Registry**: on merge, the 5 rows flip `approved → implemented`.

## Manual impact

`docs/manual/user/import.md` (manual import flow; embedded-metadata matching;
tagging option), `docs/manual/user/web-ui.md` (overlay), and
`docs/manual/admin/configuration.md` (tagging toggle). Declared per FRG-PROC-011.

## Approval

- **Approver:** Adrian
- **Date:** 2026-07-06
- **Decision:** Approved under the M2/M3 standing grant of 2026-07-06 covering
  the 6-change M2 decomposition (this is change 2, with FRG-PP-017/IMP-024
  placed here so the metadata read/write halves land together beside the manual
  matching they strengthen).
