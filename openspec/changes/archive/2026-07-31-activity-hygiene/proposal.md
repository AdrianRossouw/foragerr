# activity-hygiene — a queue you can read and clean

## Why

Owner dogfood 2026-07-30: "there's a rendering issue on the wanted queue.
and there's a bunch of stuff that failed. not sure how to clean up that
queue easily." Measured on the live deployment at 1440px:

- The queue table overflows its frame sideways: every column is
  `white-space: nowrap`, the title column holds unbreakable dotted
  release tokens, there is no scroll wrapper, and the actions cell's
  flex-on-td opts it out of column negotiation — so the per-row action
  buttons render clipped past the right edge (Failed rows show no
  reachable actions at all), and the whole page scrolls sideways.
- Failed rows carry meaningless "0%, 0 B left of 0 B" progress bars and
  raw download hashes where a title should be.
- The screen is hard-capped at page 1 of 20 rows with no paging
  controls, and there is no bulk affordance of any kind: 5 failed +
  5 import-blocked rows must be removed one dialog at a time. Failed
  rows are permanent residents — nothing ever cleans them up.

Per-row remove with delete-data and blocklist options already exists end
to end (FRG-UI-006 / the DELETE endpoint); this change gives it reach.

## What Changes

- **The queue table stays inside its frame** (MODIFIED `FRG-UI-006`):
  a scroll-contained table sharing the app's data-table styles, wrapping
  release tokens instead of forcing page-wide horizontal scroll, with
  the actions column always reachable. Failed rows drop the progress
  bar/byte noise (status and reason carry the information); a row whose
  release name is an opaque token still reads by its series/issue
  columns.
- **Selection and bulk cleanup** (MODIFIED `FRG-UI-006`): checkbox
  selection with select-all (the Blocklist screen's established
  pattern), a bulk Remove using the same delete-data/blocklist dialog,
  and a one-click **Clear failed** that selects-and-removes every
  failed row. Paging controls appear (the same component the Blocklist
  and History screens use).
- **A bulk remove endpoint** (MODIFIED `FRG-DL-008`): one request
  removes many tracked rows with the same per-row semantics the single
  DELETE has (409-while-importing per row, optional blocklist write,
  best-effort client removal), returning the per-row applied/errors
  shape the sources bulk endpoint established.

## Capabilities

### Modified Capabilities

- `ui`: MODIFIED FRG-UI-006 (contained table, honest failed rows,
  selection + bulk remove + clear-failed, paging).
- `dl`: MODIFIED FRG-DL-008 (bulk remove contract on the queue view).

## Impact

- Frontend: `QueueScreen.tsx` + module CSS (compose
  `dataTable.module.css`, add `tableWrap`, selection column, bulk bar,
  `PageControls`), `RemoveQueueDialog` reused for bulk.
- Backend: `api/queue.py` gains `POST /queue/remove` (ids + blocklist +
  deleteData) looping the existing single-row semantics in one handler;
  no schema change, no new dependency, no new attack surface (same
  authenticated surface, same mutations already reachable one-by-one).
- Manual: `docs/manual/user/web-ui.md` queue section.

## Non-goals

- Retry of a failed grab (FRG-DL-014, milestone B — untouched).
- Tracked-download retention/auto-expiry of failed rows — recorded as a
  follow-up idea; explicit cleanup solves the felt pain without a
  policy decision.
- Any change to failure handling, blocklist semantics, or auto
  re-search (FRG-DL-011..013).

## Approval

Owner go 2026-07-30, on the diagnosis and plan as presented ("nope.
sounds good." to the queued order, following "not sure how to clean up
that queue easily"); approval carried into 2026-07-31's "approve and
continue with the next items".
