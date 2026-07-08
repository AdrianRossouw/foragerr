# Design: m3-volume-grouping (M3 change 4)

Additive franchise grouping over the one-series-per-CV-volume model. The invariant:
grouping touches **display only** — `wanted_issues()` (`library/repo.py:234`) and
`series_statistics` are never given a group/type predicate.

## 1. Model

- New `series_groups` table: `id`, `title` (display), `grouping_key` (normalized,
  UNIQUE), `manual_title` (bool — operator renamed it, so a re-derivation won't
  relabel), `created_at`. A group has NO files/monitor/wanted state.
- `SeriesRow` gains `series_group_id` (nullable FK → `series_groups`, `ON DELETE SET
  NULL`) and `group_locked` (bool default false — operator reassigned/detached this
  series, so auto-derivation skips it). Both additive/nullable-or-defaulted; must not
  trip `test_repo_hygiene` (no `wanted` column; CHECK constraints intact).
- Migration `0013_series_groups`, `down_revision="0012_issue_file_page_count"`,
  forward-only (`downgrade` raises).

## 2. Franchise key (the derivation)

`franchise_key(title)` = strip a trailing volume-year `(YYYY)` and a trailing
`Vol N`/`Volume N` designator from the title, then `parser.normalize.matching_key(...)`
(the existing fold). So "Batman (2011)" and "Batman (2016)" → key `"batman"`. An empty
result (untitled edge) → no group. This lives in `library/grouping.py` (new) reusing
`parser.normalize`; it is pure and unit-tested against real title shapes.

## 3. Auto-grouping + override

- At **add** (`library/flows/add.py`) and **refresh** (`library/flows/refresh.py`):
  compute `franchise_key(series.title)`; if the series is not `group_locked`,
  find-or-create the `series_groups` row for that key and set `series_group_id`. A
  `manual_title` group keeps its title; a fresh group's title defaults to the series'
  franchise-stripped display title.
- **Override** (FRG-SER-017), via the series edit flow (`flows.edit_series`, the
  `aliases`-override precedent): reassign (`series_group_id = X`, `group_locked = true`),
  detach (`series_group_id = null`, `group_locked = true`), rename group (`title = ...`,
  `manual_title = true`). Clearing the lock re-derives on next refresh. A group left
  with zero members after a reassignment is pruned (or left empty and filtered from the
  projection — implementer's call; prefer prune to avoid orphan rows).

## 4. Grouping projection (FRG-API-020) — bounded aggregation

`GET /api/v1/series/groups`: a SINGLE aggregate query joining `series_groups` ← `series`
← `issues`/`issue_files`, `GROUP BY series_groups.id`, yielding per-group series count,
total issue count, owned (file-backed) count — NOT the per-series `series_statistics`
path run per group (that is the known N+1; do not multiply it). Ungrouped series
(`series_group_id IS NULL`) are returned as singleton franchises (keyed by the series
id) so the view is total. Standard paging envelope. `SeriesResource` gains
`series_group_id` so the flat list needs no second call.

## 5. Grouped view (FRG-UI-021)

`screens/library/LibraryIndex.tsx`: add a grouped display mode (a 4th toggle beside
poster/overview/table, or an orthogonal "group by franchise" switch on top of the
current mode — implementer picks the cleaner UX in the existing `useUiStore` view
state). Render franchise headers (title + roll-up stat) with member runs nested and
collapsible; a single-run franchise renders as an ordinary row (no group chrome). Data
via a new `useSeriesGroups()` hook over `GET /series/groups`. Reuse existing
`PosterCard`/`SeriesTable` row rendering for the members. Per-series actions/navigation
unchanged. Rename/reassign affordance reachable from the group header (calls the edit
flow). Keep it Sonarr-shaped; the parked `Foragerr.dc.html` mockup's group chips are a
later design-milestone restyle, not this change.

## 6. Work-area partition (FRG-PROC-008)

- **A — backend** (`library/models.py`, migration `0013`, new `library/grouping.py`,
  `library/flows/add.py`+`refresh.py`, `library/repo.py`, `api/series.py`): the model,
  franchise-key derivation, auto-group + override persistence, the aggregate grouping
  query, `GET /series/groups`, and `series_group_id` on `SeriesResource`. SER-016,
  SER-017, API-020. HIGH-MEDIUM subtlety (the non-regression of wanted/stats is the
  correctness core; prove it with a test asserting `wanted_issues` output is identical
  before/after grouping).
- **B — frontend** (`screens/library/`, `api/hooks.ts`, `api/types.ts`, `store/`):
  grouped display mode + hook + type field + the rename/reassign affordance. UI-021.
  Depends on A's endpoint contract.
- **C — docs/traceability/gate**: user manual (grouped view + correcting a group),
  registry flip + matrix, review cycle + merge + v0.3.2.

## Open Questions

None blocking. Defaults: (1) grouped mode = an orthogonal "group by franchise" toggle
over the current poster/table mode (not a 4th mutually-exclusive mode) — simplest and
composable; flip to a 4th mode if the toggle is awkward. (2) An emptied group is pruned
on reassignment. (3) `franchise_key` strips only a *trailing* `(YYYY)`/`Vol N` — a
year mid-title (rare) is left alone to avoid over-merging distinct titles.
