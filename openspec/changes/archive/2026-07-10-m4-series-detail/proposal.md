# m4-series-detail — series detail to the M4 design + trade containment (M4 ch4)

## Why

The series-detail screen is still the M1 visual language inside the v0.4
shell, and the owner's demo review surfaced concrete UX failures on it: the
bulk-monitor action is an unlabeled icon button he could not find, there is
no range/select-all selection, and long overviews swamp the page. The design
handoff specifies the replacement (blurred-cover hero, Issues/Collections
panel), and the roadmap-reshape assigned the trade "collected in"
containment model — deferred from M3 — to this change. Research
(2026-07-10) confirmed the viable v1: operator-declared ranges in a
display-only side table; ComicVine's structured "collects" links are
stripped by our sanitizer at ingest, so description-derived suggestions are
deferred.

## What Changes

- **MODIFIED FRG-UI-004 — Series detail screen**: rebuilt to the design —
  blurred/darkened cover backdrop hero with the sharp 206×309 cover, 33px
  title, monitored + publisher + first-issue + status + issue-count + format
  meta row, icon-over-label action row (Search Monitored, Search All,
  Refresh, Edit, Delete), and the overview paragraph **collapsed behind a
  "show more" toggle when long** (owner request). Below: a bordered panel
  with an `Issues · N / Collections · N` segmented toggle and a compact
  progress bar; the Issues tab is the design's dense table (monitor, Issue,
  Release, Status pill, Collected in chips, Size, per-row search/⋯ actions).
  Existing behavior (per-issue monitor toggles, searches, commands, local
  covers) is unchanged.
- **ADDED FRG-UI-025 — Issue bulk selection and actions**: per-row
  checkboxes with **shift-click range selection**, a header select-all /
  deselect-all, and — when a selection is active — a **labeled bulk-action
  bar** (Monitor, Unmonitor, Search selected) replacing the current
  unlabeled header bookmark button (owner request).
- **ADDED FRG-SER-020 — Trade containment model (declared, display-only)**:
  a new `issue_collections` side table (migration 0015) mapping a
  trade-typed series' issue (one collected book) to a target series plus an
  ordering-key–bounded contiguous range, one row per sub-range
  (non-contiguous and multi-series omnibus = multiple rows). Declared by
  the operator; `source`/`confidence` columns ship ready for later derived
  suggestions. Containment is display-only by construction: no column on
  `series`/`issues`, and the FRG-SER-019 absence test is extended to prove
  `wanted_issues`/`series_statistics` never reference the new table.
- **ADDED FRG-API-022 — Containment resources**: collected-in chips data on
  the issues list, a per-series collections rollup (each collected book with
  its declared ranges, release info, and a singles-coverage status computed
  read-only: Collected / Partial / Not collected), and declare/edit/delete
  endpoints for ranges.
- **ADDED FRG-UI-026 — Collections tab**: the design's collections list
  (format chip, "Collects #a–#b", counts, coverage status) with an edit
  affordance opening a containment dialog (target series from the library,
  start/end issue pickers, multiple sub-ranges); "Open" navigates to the
  trade series' detail.
- **MODIFIED FRG-SRCH-008 — Search All scope** (amendment, found during
  implementation): `SeriesSearchCommand` gains `monitored_only` (default
  true) honored via a new `missing_issues()` sibling selectable, so the
  detail screen's "Search All" genuinely covers unmonitored missing issues;
  reachable only from the explicit operator action — schedulers and chained
  searches stay wanted-scoped, and `wanted_issues()` is untouched.
- **Cleanup (no spec change)**: the grouped-library franchise ⋯ popover
  mirrors the shared Menu primitive's a11y behavior (panel role, focus on
  open, Escape restore — behaviors aligned rather than the component
  swapped, since the shared trigger styling doesn't fit an inline ⋯
  button), closing the ch2 review deferral (FRG-UI-021).
- New registry IDs allocated at proposal time: FRG-SER-020, FRG-API-022,
  FRG-UI-025, FRG-UI-026.

## Non-goals

- **No acquisition semantics from containment** — it never marks singles
  wanted/monitored, never feeds the pull matcher (FRG-SER-019 stays
  mechanically proven); the Collections tab drives no downloads.
- **No description-derived containment suggestions** in this change (the
  sanitizer strips CV's `data-ref-id` links; a suggestion pipeline is
  backlog — the schema's `source`/`confidence` columns are ready for it).
- **No story-arc / reading-list model** (Mylar's storyarcs is an
  acquisition engine; explicitly out).
- **No ComicVine discovery of not-in-library trades** on the Collections
  tab (the tab lists declared containment for the viewed series; remote
  trade discovery belongs to the add-new flow).
- No creator credits on the hero (data arrives with M5 creators).

## Capabilities

### New Capabilities

- none (requirements slot into existing capabilities: ser, api, ui, db via
  migration).

### Modified Capabilities

- `ui`: MODIFIED FRG-UI-004 (redesigned detail); ADDED FRG-UI-025 (bulk
  selection), FRG-UI-026 (Collections tab).
- `ser`: ADDED FRG-SER-020 (containment model).
- `api`: ADDED FRG-API-022 (containment resources).

## Impact

Backend: migration `0015_issue_collections` (association table per the 0013
FK pattern), repo reads/writes (rollup queries modeled on the display-only
grouping layer), containment API endpoints, FRG-SER-019 absence-test
extension; pytest per scenario. Frontend:
`screens/series/SeriesDetail.tsx` rebuild + module CSS, bulk-selection
state/UX, Collections tab + containment dialog, show-more overview;
vitest per scenario; e2e selectors (`issue-row-<id>`, per-row search button
names, `interactive-search-overlay`, `command-status` are contract — keep).
Docs: manual series page + web-ui section (manual impact: those two);
`docs/security/`: containment write endpoints recorded (same no-auth
acceptance lineage; tampering note). SOUP: none. Gate tier: **LARGE**
(size + new write surface + wanted-invariant adjacency) — full fleet +
Codex, with a dedicated invariant angle.

## Approval

Covered by the owner's 2026-07-10 standing grant (M4–M7); recorded per
FRG-PROC-009.
