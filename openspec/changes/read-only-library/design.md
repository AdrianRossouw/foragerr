# read-only-library — design

## Context

A library root today must be writable (`api/library_config.py`
`_validate_new_root` → `os.W_OK`), because the library *manages* files:
Library Import renames to canonical names / moves into per-series folders,
per-series rescan can move files, and the acquisition path downloads
missing issues into the root. OPDS then serves the tracked `issue_files`.
A read-only mount has nothing writable, so it is refused (finding #4).

## Goals / Non-Goals

**Goal**: register a real collection read-only; index it in place (no disk
mutation); serve it over OPDS; never acquire into it. **Non-goals**:
acquisition into a RO library, blended RO/RW roots, the parser-heuristics
pre-design, OPDS facet browsing.

## Decisions

**D1 — `read_only` is a persisted flag on the root, and the write boundary
is enforced fail-closed at each write path, not only at the UI.** The
root-folder row gains `read_only` (additive column). Registration for a RO
root swaps the `W_OK` check for an `R_OK`/exists check. Every disk-write
path gains a guard keyed on "is this series' root read-only": import
placement, rescan moves, the download/import writer, and the recycle-bin
delete. Rationale: the feature's entire value is *not touching* the
operator's files; a UI-only suppression would still write if any code path
reached it. The gate audits every write path and tests assert zero writes
under a RO root. Alternative — a global "dry-run" flag — rejected: too
coarse, and it wouldn't let RO and RW roots coexist.

**D2 — Index-in-place is the existing import with the placement step made a
no-op.** Reuse scan → match → register wholesale; for a RO root the
"build series path / rename / move" step becomes "register the series at
the files' existing folder and record `issue_files` at their real paths."
No naming template, no move. This keeps one import pipeline rather than a
parallel RO importer. FRG-IMP-027 (atomicity) is moot here — nothing on
disk changes — but a RO series is still only created when its files index,
so a failed index leaves no series.

**D3 — A read-only series is acquisition-inert by construction.** Rather
than scatter "if read_only" through monitoring/wanted/search/grab, gate at
the entry points: a RO series is created unmonitored and its
monitor/search/grab/delete-files operations refuse with a clear reason
(one guard helper, `series_is_read_only(series)`), and the derived
wanted/calendar projections exclude RO series from the acquisition
surfaces. The UI (FRG-UI-045) mirrors this by hiding the affordances.
Rationale: fewer, centralized guards; the wanted/search machinery stays
unaware of RO beyond the exclusion.

**D4 — Metadata and covers never touch the root.** Metadata refresh writes
to the DB and cover caching to the config dir already (not the root), so
RO series refresh and get covers with no change — confirm the cover cache
path is config-dir-rooted (it is: `metadata/covers`), so nothing to gate
there.

## Risks / Trade-offs

- [A missed write path mutates the operator's real files] → the core risk;
  mitigated by a centralized "root is read-only" guard applied at each
  write path, a gate-time audit enumerating write paths, and tests that
  assert no on-disk change under a RO root across import/rescan/download/
  delete. This is why the change sequences AFTER the import-atomicity fix,
  whose write-path work maps the same surface.
- [A RO series leaking into wanted/search/calendar] → D3's entry-point
  guards + projection exclusion; tested.
- [Scale: indexing a multi-thousand-issue real library] → the same scan/
  match path as a normal import; this change is the first at-scale
  exercise (a stated goal). Watch scan throughput (FRG-NFR scan budget)
  and CV budget for metadata refresh across many new series — likely a
  follow-up tuning item, surfaced by the dogfood, not blocking.

## Migration Plan

Additive `read_only` boolean on the root-folder table (default false, so
existing roots are unaffected). No data rewrite. Rollback = revert + drop
column inert to older code.

## Open Questions

- Whether a RO series should still appear in the Calendar as *released/
  owned* context (read-only, informational) or be excluded entirely.
  Leaning: it can appear as owned context but exposes no acquisition
  action — decide at implementation.
- Bulk-registering a large existing library: one root + one big index, or
  a guided first-run? Out of scope for the minimal shape; the plain
  scan+import covers it, scale behavior TBD from the dogfood.
