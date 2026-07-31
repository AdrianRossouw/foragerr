# library-sorts — sort the shelf by size on disk and latest issue

## Why

Owner ask 2026-07-30: "can we also do a sort by size on disk on the main
shelf. oh and sorted by latest issue." The series index already carries
per-series statistics (size on disk, last/next release dates) in the
payload the screen holds; the sort menu just never offered them.

## What Changes

- MODIFIED `FRG-UI-003` (complete restatement): the Sort menu gains
  **Size on disk** (aggregate file bytes, largest first) and **Latest
  issue** (most recent known release date, newest first, undated last),
  both persisted like the existing choices. Client-side comparators over
  the statistics already in memory — no API change.

## Capabilities

### Modified Capabilities

- `ui`: MODIFIED FRG-UI-003 (two sort options).

## Impact

Frontend only: `LibraryIndex.tsx` comparators + menu rows,
`store/uiStore.ts` LibrarySortKey/whitelist/rehydration guard, tests.
Manual: the library page's sort list if enumerated. No backend, no new
attack surface.

## Non-goals

Server-side sorting (the index intentionally sorts client-side over the
full library); grouped-view ordering (grouping still disables the menu).

## Approval

Owner ask 2026-07-30 ("nope. sounds good." to the queued plan), carried
by 2026-07-31 "approve and continue with the next items".
