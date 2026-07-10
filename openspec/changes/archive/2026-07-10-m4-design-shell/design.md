# m4-design-shell — design

## Context

First change of the M4 design refresh (standing grant 2026-07-10). Source of
truth: the owner's design handoff (outside the repo; layout skeleton, token
tables, and component inventory reviewed 2026-07-10). Current UI: M1-era
chrome, CSS-variable token layer (FRG-UI-002), React SPA with React Query +
WS invalidation (FRG-UI-001), header quick-search (FRG-UI-019).

## Goals / Non-Goals

**Goals**: the handoff's app frame and token set, shipped-screens-only nav,
live nav counts, one-command screenshot refresh, spine green throughout.
**Non-goals**: screen redesigns (ch2–ch6), Calendar/Creators nav, behavior
changes.

## Decisions

1. **Tokens as CSS variables, one theme file.** The handoff palette lands in
   the existing token layer's mechanism (FRG-UI-002 keeps its architecture;
   values and scale change). Publisher tint/accent maps are data (TS
   constants) feeding inline styles, not per-publisher CSS classes.
2. **Fonts and icons self-hosted.** Roboto (300/400/500/700) woff2 files and
   Font Awesome 6 Free vendored under `frontend/` static assets — no CDN
   (SSRF/egress posture, offline tailnet operation). If FA6's package footprint
   is disproportionate, subset to the used glyph set; decision recorded in the
   implementation commit. SOUP: build-time asset packages register as frontend
   tooling if added to package.json.
3. **Shell = layout components, screens unchanged.** `AppShell` (Sidebar,
   GlobalHeader, PageToolbar slot, scrollable Main) wraps existing routes.
   Nav count badges read existing endpoints (series stats, queue, wanted)
   via React Query with WS invalidation — no new API surface.
4. **Nav shows shipped screens only** (Comics, Wanted, Activity, Settings,
   System). Calendar/Creators enter with their screens. The design's exact
   visual order is preserved for the entries that exist.
5. **Screenshot refresh is a gate tool, spec'd as FRG-PROC-017.**
   `tools/refresh-readme-shots.sh`: start backend against the PD demo library
   (`/comics`), populate if empty, run the capture script, optimize ≤300 KB,
   exit non-zero on any missing shot. The FRG-PROC-017 test asserts the tool
   exists/executes `--help` and that README assets match the capture set;
   actually running it stays a merge-gate step for UI-affecting changes
   (same test-vs-gate split as the history scan).

## Risks / Trade-offs

- [e2e selectors break with the new chrome] → keep `data-testid`s stable;
  spine run is part of this change's gate.
- [FA6/Roboto bloat the image] → subset/tree-shake; size delta reported at
  gate.
- [Nav counts add polling load] → reuse existing React Query caches +
  WS invalidation; no new endpoints, no timers.

## Migration Plan

Pure frontend + tooling; no schema/config changes. Rollback = revert.

## Open Questions

- None.
