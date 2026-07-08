## Why

foragerr models each ComicVine **volume** as one `SeriesRow` (FRG-SER-001). But in
comics a "volume" is a *run* — "Batman (2011)", "Batman (2016)", "Batman (2025)" are
three CV volumes of one franchise — and ComicVine has **no franchise/title entity** to
group them. So the library today is a flat one-row-per-run list: the three Batman runs
scatter alphabetically among everything else, and there is no way to see "all of
Batman" as a unit. This is the comics-native gap M3 change 4 (volume-grouping) closes.

Grouping is **ours to derive** (a name heuristic over the runs) and **ours to let the
operator correct** (merge/rename/reassign), and it is strictly **additive**: a group
is a display grouping over series, never a change to what a series *is*. The flat
series view stays; a new grouped view sits beside it. Nothing about identity,
matching, monitoring, or wanted state changes — this change adds a grouping dimension
and the view that renders it.

## What Changes

- **Volume grouping model + franchise derivation (FRG-SER-016, NEW)** — a new
  `series_groups` table (a franchise/title group with a display title and a normalized
  grouping key) and a nullable `SeriesRow.series_group_id` link. A series' group is
  **auto-derived** from its title by a franchise key: the existing normalization
  (`parser.normalize.matching_key`) with trailing volume-year / `Vol N` designators
  stripped, so "Batman (2011)" and "Batman (2016)" fold to the same key and share a
  group. Grouping is find-or-create at add and refresh; a series with no confident
  group simply stays ungrouped (its own de-facto group of one in the view). No issue,
  file, monitor, or wanted behavior is touched.

- **Grouping manual override survives refresh (FRG-SER-017, NEW)** — the operator can
  correct the heuristic: rename a group, or reassign a series to a different group (or
  detach it). A reassigned series is **locked** (`group_locked`) so a later
  `refresh-series` never re-derives over the operator's choice — mirroring the existing
  `aliases` user-override precedent (FRG-SER edit flow). A renamed group keeps its
  identity across refreshes.

- **Series grouping projection (FRG-API-020, NEW)** — a read projection the grouped
  view consumes: franchise groups each with their member series and an **aggregated**
  stat roll-up (series count, total/owned issues), computed without multiplying the
  existing per-series statistics N+1. Delivered as a dedicated `GET /api/v1/series/groups`
  read endpoint (standard paging envelope, FRG-API-006/002); the flat `GET /series`
  list is unchanged, and each `SeriesResource` gains its `series_group_id` so the flat
  view can show a group affordance too.

- **Grouped library view (FRG-UI-021, NEW)** — the Comics screen gains a **grouped**
  display mode alongside the existing poster/overview/table modes: franchise headers
  (title + roll-up stat) with their runs nested beneath, collapsible, in the current
  Sonarr-shaped style. A single-run franchise renders as a normal row. The flat views
  are unchanged; the mode is a toggle in the existing view state.

## Capabilities

### New Capabilities

- `ser`: FRG-SER-016 (grouping model + franchise derivation), FRG-SER-017 (manual
  override survives refresh).
- `api`: FRG-API-020 (series grouping projection).
- `ui`: FRG-UI-021 (grouped library view).

## Impact

- **Code**: backend + frontend. New `series_groups` table + `SeriesRow.series_group_id`
  / `group_locked` columns under a forward-only migration `0013`; a franchise-key
  helper (in `parser/normalize` or a `library/grouping` module) that strips
  volume-year/`Vol N` before folding; find-or-create-group wired into the add and
  refresh flows (`library/flows`); an aggregated grouping query in `library/repo`
  (avoiding the per-series stats N+1); `GET /series/groups` in `api/series.py` +
  `series_group_id` on `SeriesResource`; a group reassign/rename/lock path on the edit
  flow. Frontend: a grouped display mode in `screens/library/LibraryIndex.tsx` + the
  data hook + `SeriesResource` type field.

- **DB**: one new table (`series_groups`) + two additive nullable/defaulted columns on
  `series` under migration `0013` (rides FRG-DB-002/008; no DB *requirement* change).
  Must not trip the schema-hygiene test (no `wanted` column, CHECK constraints intact).

- **Security** (FRG-PROC-006): **none.** No new listener, parser of untrusted input,
  credential, or outbound integration — grouping is a derivation over existing local
  metadata and an operator override. No threat-model or risk change.

- **Manual** (FRG-PROC-011): **user-facing.** `docs/manual/user/` (library/browsing
  section) documents the grouped view and how to correct a group (rename/reassign);
  no admin change. README labelling if it enumerates library views.

- **Dependencies / SOUP** (FRG-PROC-012): **none.**

## Non-goals

- **No change to series identity, matching, monitoring, or wanted/missing state.**
  Grouping is display-only over `SeriesRow`; `wanted_issues()` and `series_statistics`
  are untouched. A group is never a monitored entity and has no files.

- **No automatic franchise metadata** (no shared franchise cover/description fetch, no
  cross-run reading order). A group's display title is the derived/edited name; richer
  franchise metadata is out of scope.

- **No grouping of trades with their single-issue runs.** Collected-edition (trade)
  typing is M3 change 5 (m3-trade-typing); this change groups *runs* by franchise. A
  trade line is just another series and groups by its own title here; change 5 adds the
  type, and the grouped view will render trades within a franchise once that lands.

- **No bulk group operations UI** beyond rename/reassign/detach (bulk is FRG-SER-015,
  backlog).

## Approval

Pre-approved under the standing M2/M3 FRG-PROC-009 grant (2026-07-06). On 2026-07-08
Adrian directed taking **M3 changes 4 and 5** next ("do 4 + 5"), with the pull screen
(change 2) still parked pending his Fable design review. The grouped view is built in
the current Sonarr-shaped style; the parked `Foragerr.dc.html` mockup (which sketches
franchise group chips) informs a later design-milestone restyle, not this change's
functional scope. Recorded per the standing-grant model used across M2/M3.
