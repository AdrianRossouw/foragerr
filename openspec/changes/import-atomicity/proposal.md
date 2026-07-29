# import-atomicity — a failed group import leaves no zombie series shell

## Why

Live dogfood (owner, 2026-07-29): importing a series through Library
Import "showed an error message but then somehow completed behind the
scenes." Root cause, confirmed in `library/flows/library_import.py`:
`_import_group` does three steps in order — **create the series**
(`add_series`, committed immediately), **fetch its issue list**
(`_refresh_before_import`), then **attach the files** — and nothing rolls
the series back if a later step fails. A transient ComicVine error at the
refresh step returns `"refresh-failed"` and surfaces that error to the
operator, but the series row it just created is already in the library as
an issueless **shell**. From there the normal machinery takes over on its
own schedule: the series is monitored, the next scheduled metadata refresh
populates its issues, and the backlog search grabs them — so the operator
sees a failure, then later sees the series "complete" without them, files
possibly re-downloaded rather than imported from disk.

This is exactly the import hardening written up but never built — item 7
of the parked `m11-import-intelligence-predesign` ("a failed add never
leaves a zombie series shell (create-then-attach is atomic per group, or
the shell is rolled back); per-group failure reasons logged at WARNING").
The 21-findings M11 that shipped reused that pre-design's name for
different content, so this original import-UX item is still open — a real
defect, not a regression.

## What Changes

- **Per-group import is atomic on the series shell** (new `FRG-IMP-027`):
  a Library Import group that creates a NEW series but does not reach an
  imported (or honestly partial-with-files-attached) outcome leaves **no
  series row behind** — the just-created series (and its
  add-side effects: monitored flags, enqueued refresh/search) are rolled
  back or never committed until the group's files are actually attached.
  The group's staging row still records the honest failure reason
  (unchanged), but the library does not silently gain a monitored,
  soon-to-be-auto-grabbed shell for a group the operator was told failed.
- Scope of "did not reach imported": the existing per-group outcomes that
  today leave a created series behind — `refresh-failed`, and any
  post-add exception (`errored`) — no longer persist the series. A group
  that genuinely imports at least one file keeps its series (unchanged); a
  group whose files are all *blocked* with the series freshly created is
  covered by the same rule (no files attached ⇒ no shell), while a
  reused/pre-existing series is never touched (only a shell THIS group
  created is rolled back).
- Re-running the scan/import for a rolled-back group behaves as a first
  run (no "volume already in library / duplicate" false block from a
  leftover shell).

## Capabilities

### New Capabilities

None — extension of the existing library-import flow.

### Modified Capabilities

- `imp`: ADDED FRG-IMP-027 (per-group import atomicity — no zombie series
  shell on a failed group).

## Impact

- Backend: `library/flows/library_import.py` `_import_group` — wrap
  create → refresh → attach so a NEW series created for the group is
  rolled back (or its creation deferred) when the group does not attach
  any files; ensure the add's enqueued refresh/search side effects don't
  outlive the rollback. `library/flows/add.py` may need a
  "create-but-defer-commit" or a compensating delete seam.
- Tests: a group whose refresh fails leaves no series row and no monitored
  issues; re-run imports cleanly; a genuinely-imported group is unchanged;
  a reused/pre-existing series is never deleted; the failure reason still
  shows on the staging row.
- No dependency changes; no new attack surface. Migration: none
  (behavioral). Manual: `docs/manual/user/import.md` (a failed group
  leaves nothing half-added).

## Non-goals

- The rest of the parked import-heuristics pre-design (filename
  segmentation, flat multi-series folder placement, edition-preference) —
  those are their own future changes; this is only the atomicity item.
- Read-only / browse-only library roots (finding #4) — separate feature.
- Any change to how a *successful* or *genuinely partial* import behaves.

## Approval

Proposed post-M11, awaiting owner approval (FRG-PROC-009) — the M11
standing grant covered the milestone's five changes and closed at
milestone end; this is new work. Written up at the owner's request after
the 2026-07-29 dogfood repro.
