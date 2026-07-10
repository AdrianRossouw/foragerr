# m4-library-views — the library's three views (M4 change 2)

## Why

M4 change 2 rebuilds the home screen to the owner's design: three view modes
over one library — a poster grid with selectable sizes and stacked
grouped-volume cards, a horizontal overview list, and a dense table — with the
design's toolbar (view switcher, Options/Sort/Filter dropdown menus) and count
line. Today's screen has poster/table/grouped modes in the M1-era visual
language; this change brings the layout, density, and menu system to the
design inside the v0.4.0 shell.

## What Changes

- **MODIFIED FRG-UI-003 — Library index screen**: three view modes — Posters
  (responsive `auto-fill` grid, S/M/L poster sizes 134/162/196px; each card =
  2:3 cover with monitor bookmark chip, publisher + volume chips, an
  owned/total progress strip whose track color reflects completeness, title +
  subline), Overview (cover thumb, title, status pill, publisher/meta, wide
  progress bar, % complete), Table (dense: monitor icon, Title+volume,
  Publisher, Issues mini-progress, Status, Year). Above the content: a count
  line (`N comics · N monitored · N with missing issues`, semantic colors).
  Toolbar: view switcher + Options (poster size segmented control, group
  toggle) / Sort (Title, Publisher, Issues owned, Year — check on active) /
  Filter (All, Monitored, Missing issues, Continuing — each with a count)
  dropdown menus in the design's raised-menu style; a click in the content
  region closes any open menu. View mode, poster size, sort, and filter
  persist across sessions (existing persistence mechanism).
- **MODIFIED FRG-UI-021 — Grouped library view**: grouped mode stacks a
  franchise's volumes into one card with the design's layered-shadow offset
  and an `N vols` chip; summed owned/total on the progress strip. Behavior
  (grouping semantics, wanted non-regression) unchanged.
- **Brand mark adopted (updated 2026-07-10 handoff)**: the handoff now ships
  the logo as SVG assets with an exact lockup spec. The sidebar tile's
  Font Awesome placeholder is replaced by the real ant-in-hexagon mark
  (inline SVG in the icon set, colors via new `--color-logo-*` /
  `--shadow-logo-tile` tokens per FRG-UI-002), the lockup styled to spec
  (32px radius-8 155° gradient tile, Roboto 900 19px wordmark), and an SVG
  favicon added. Implementation refinement within FRG-UI-023's existing
  "logo lockup" text — no spec delta, no new IDs.
- Tour regenerated (FRG-PROC-017) — the grid screenshot shows the new cards.

## Non-goals

- No changes to grouping semantics, filtering/search behavior at the API, or
  wanted computation — visual/UX layer only, existing endpoints.
- No series-detail changes (ch3); no Calendar (ch5).
- Publisher tint/accent backgrounds before cover art loads are in scope only
  as far as the palette maps from ch1 allow — no new metadata fetches.

## Capabilities

### Modified Capabilities

- `ui`: FRG-UI-003 (three views, menus, count line), FRG-UI-021 (stacked
  group cards).

## Impact

`frontend/src/screens/library/**` (LibraryIndex + new view components +
menus), possibly shared `Menu`/`SegmentedControl`/`ProgressStrip` primitives
under components/; vitest updates; e2e selectors (`library-poster-grid` and
SELECTORS.md — keep stable); `docs/manual/user/library.md` (view modes,
options/sort/filter) and `web-ui.md` if navigation text changes;
`docs/readme-assets/comics-grid.png` regenerated. No API/backend changes; no
SOUP changes; no new attack surface. Delta spec: ui only. No new IDs.

## Approval

Covered by the owner's 2026-07-10 standing grant (M4–M7); recorded per
FRG-PROC-009.
