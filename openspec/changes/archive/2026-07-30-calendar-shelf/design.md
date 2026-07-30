# calendar-shelf — design

## Context

v0.17.0's agenda rows optimized for density: 24px single-line rows, a
16×24 cover sliver, publisher trailing the title inline. Design session 2
(2026-07-30) measured why that fails the owner's actual use — the
calendar is a *discovery* surface ("i don't know the current comics well
enough to even consider adding them"), and discovery runs on cover art
and metadata, not row count. The session also found the publisher palette
lookup never matches live feed names (exact-match keys "Marvel"/"DC" vs
feed "Marvel Comics"/"DC Comics"), so the tint/accent signal has been
inert on real data since M4.

## Decisions

**D1 — Shelf rows, one opinionated density.** ~66×99 cover, two metadata
lines (creators; two-line clamped description), fixed-position publisher
chip, right action rail; ≈110px vertical rhythm. No user density toggle —
one layout, revisited only on evidence. Rationale: the owner picked this
against two denser variants on his own live week; a toggle would keep
two layouts alive for one operator.

**D2 — The publisher chip is a fixed-position element, not trailing
text.** Swatch + normalized name at the start of the meta cluster. This
is the direct fix for the end-of-line scan: the eye lands on one
x-position per row.

**D3 — Palette resolution normalizes, then derives.** Lookup folds
corporate suffixes (Comics/Studios/Entertainment/Publishing/…) and
matches case-insensitively against the named palette; misses derive a
stable hue from the normalized name (hash → HSL at fixed
saturation/lightness bands tuned for the dark shell), never the brand
green. Implemented in the shared `theme/palettes.ts` helpers so library
poster tints inherit the repair. The named palette stays the
authoritative source for the majors (FRG-UI-002's single-palette rule);
the derived hue is a deterministic fallback, not a second palette.

**D4 — On-row enrichment renders what exists, omits what doesn't.**
Writer/artist line and description clamp render only when stored
(pre-enrichment weeks carry nulls); the detail surface keeps the full
set (characters, UPC, full description, all roles). No layout jumps:
absent lines collapse.

**D5 — Everything else carries over untouched.** Quiet cards below
900px, honest state chips (FRG-UI-047), optimistic monitor toggle
(FRG-UI-048), add-from-anywhere (FRG-PULL-008), day grouping, filters,
lazy cover loading through the proxy (FRG-META-021). The carried
calendar-legibility tests (target floor, measure floor, refusal
surfacing) adapt their geometry, not their assertions.

## Risks / Trade-offs

- [~10 rows per screen vs 22 before] → the owner chose this trade
  explicitly; day headers + lazy covers keep long days navigable.
- [Derived hues collide between small publishers] → collisions are
  expected at real publisher counts (hundreds of names into a ~290-value
  arc); the cost is cosmetic by design — the name is always printed
  beside the swatch, and the named palette carries the majors.
- [Two-line clamp hides description tails] → full text stays on the
  detail surface; the clamp is a browse teaser, not the reading surface.

## Migration Plan

Frontend-only; no data or API change. Rollback = revert.

## Open Questions

None — the layout was picked against live data.
