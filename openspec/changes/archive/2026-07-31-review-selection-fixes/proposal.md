# review-selection-fixes — select all, and a restore that answers immediately

## Why

Owner dogfood 2026-07-31, restoring non-comic items: "when i select all
(there really should be a button) and try to restore, only some of them
are unignored and i have to refresh to see which ones."

Three causes, measured:

- **There is no select-all.** The review bar offers "Select bundle…" and
  shift-range only.
- **Bulk restore blocks on ComicVine, one row at a time.** Restore
  recomputes a proposal per row; ComicVine calls are spaced at
  `comicvine_min_interval_seconds` (2 s default), so restoring 30 rows is
  a single request that takes over a minute while committing row by row.
  A refresh mid-flight shows a partial result — which is exactly what the
  owner saw. Nothing is corrupted; the action is silently slow.
- **"Show non-comic items" does not show non-comic items.** It stops
  *excluding* them, so they arrive mixed into the current list. Selecting
  across that mix and restoring refuses every row that was never parked —
  correct per-row, but it reads as "it only worked on some".

## What Changes

- **Select all** (MODIFIED `FRG-UI-029`): a select-all control over the
  rows the current filter shows, beside the existing bundle and group
  helpers, with an explicit count and a clear affordance.
- **Non-comic becomes a filter, not a reveal** (MODIFIED `FRG-UI-029`):
  it joins New/Matched/Ignored/Duplicates as a scope with its own count,
  so a selection can never silently span classifications.
- **Bulk restore defers its proposal recompute** (MODIFIED
  `FRG-SRC-004`): a bulk restore returns as soon as the rows are parked
  back to `new`, leaving proposals for the enrichment pass — the same
  deferral the single restore already uses when the budget wall is hit.
  A single-row restore still recomputes inline.
- **The list reflects the outcome when the action reports** (MODIFIED
  `FRG-UI-029`): bulk outcomes settle their invalidation before the
  result renders, and the per-row refusals name what was refused.

## Capabilities

### Modified Capabilities

- `ui`: MODIFIED FRG-UI-029 (select-all, non-comic filter, settled bulk
  outcomes).
- `sources`: MODIFIED FRG-SRC-004 (bulk restore defers proposals, and
  the deferral must not strand a row); MODIFIED FRG-SRC-016 (non-comic
  visibility now names the filter scope, not the retired toggle).

## Impact

Frontend: StoreManage selection + filter model, bulk result handling.
Backend: `bulk_restore` skips the inline CV recompute (the deferral
semantics already exist); no schema change, no new surface.
Manual: sources review section.

## Non-goals

- Changing single-row restore's inline recompute.
- Background job orchestration for proposals (the existing enrichment
  pass already claims un-proposed rows).

## Approval

Bugfix under the standing grant (owner-reported defect, 2026-07-31);
the select-all is the owner's explicit ask in the same report.
