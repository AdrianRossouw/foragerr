# m4-shell-hotfix — tour rendering defects found post-v0.4.0

## Why

The v0.4.0 README tour shipped two defects the owner spotted: the series-detail
cover rendered as a zoomed crop (the hero flex row's default align-stretch
defeats the shared poster frame's 2:3 aspect-ratio once a description is long —
latent since change 7, exposed by Planet Comics' long deck), and the refresh
tool's fresh-database import trusted the auto-proposal, which matches "Planet
Comics" to the 1988 Blackthorne reprint volume — silently poisoning the tour
with a wrong, near-empty series.

## What Changes

- Poster frame in the series-detail hero pins to its own aspect
  (`align-self: flex-start`) so the cover always renders whole (FRG-UI-004).
- `tools/refresh-readme-shots.sh` gains a known-demo-library proposal-override
  map (folder → ComicVine volume id; Planet Comics → 816) applied via the
  existing `PATCH /library-import/groups/{id}` before execute, making the tour
  deterministic (FRG-PROC-017).
- Tour regenerated with both fixes.

## Non-goals

No screen redesign (ch3 rebuilds series detail); no import-matching changes in
the product itself.

## Capabilities

### Modified Capabilities

(none — defect fixes within existing requirements FRG-UI-004, FRG-PROC-017.)

## Impact

`frontend/src/screens/series/SeriesDetail.module.css`,
`tools/refresh-readme-shots.sh`, `docs/readme-assets/*`. Manual impact: none.
SOUP: none.

## Approval

Covered by the 2026-07-10 M4–M7 standing grant; defect flagged by the owner
("there is also a rendering issue in the series detail screenshot").
