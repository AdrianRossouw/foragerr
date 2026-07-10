# m4-library-views — design

## Context

M4 ch2 (standing grant). Source: the owner's design handoff §1 (library) and
§Overlays (menus) — re-extract from the gitignored zip in docs/research/ if
needed. Inside the v0.4.0 shell and ch1 tokens/palettes.

## Decisions

1. **Existing data flow untouched** — same queries, grouping projection, and
   filter semantics; this is a presentation rebuild of LibraryIndex and its
   view components.
2. **Primitives extracted once**: ProgressStrip (owned/total + track color),
   Chip, Menu/Dropdown (raised style, outside-click close), SegmentedControl
   — these serve ch3–ch6 too; tokens-only styling.
3. **Persistence** uses the screen's existing view-state persistence
   mechanism, extended to poster size and filter.
4. **Stacked group card** is a poster-mode rendering of the existing grouped
   projection — no new grouping logic; layered shadow via the ch1 shadow
   tokens.

## Risks / Trade-offs

- [e2e selector breakage] → `library-poster-grid` and SELECTORS.md entries
  kept stable; spine at the gate.
- [Menu a11y] → menus are keyboard-reachable (esc closes, arrows navigate)
  even though the design only shows mouse flows.

## Migration Plan

Frontend-only; rollback = revert.

## Open Questions

- None.
