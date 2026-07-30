# calendar-shelf — the calendar as a browsable shelf

## Why

Owner feedback in design session 2 (2026-07-30), on the shipped v0.17.0
agenda rows: the covers are too small to carry information (16×24 px, the
one-line density cap), useful metadata is hidden behind the expando, and
on a wide screen the publisher trails the variable-length title inline —
"I have to scan to the end of the line to see whether it's DC or Marvel."
The session also measured a live defect: the publisher tint/accent palette
keys ("Marvel", "DC", "Image") never match the feed's names ("Marvel
Comics", "DC Comics", "BOOM! Studios"), so the one at-a-glance publisher
signal has been silently falling back to the brand green on essentially
every live entry.

The owner reviewed three interactive variants built from a live week of
his own data and picked the shelf: "honestly, the shelf feels most
comfortable. i don't know the current comics well enough to even consider
adding them. this greatly aids discoverability. so C."

## What Changes

- **Shelf rows above the crossover** (MODIFIED `FRG-UI-018` — complete
  restatement): each entry renders a ~66×99 cover, title + issue with a
  fixed-position publisher chip (swatch + normalized name), a
  writer/artist line, up to two clamped lines of the stored description,
  and a right-aligned state/action rail. The v0.17.0 36px density ceiling
  is deliberately retired — the calendar is a discovery surface, and the
  cover plus on-row metadata are the browsing material. The quiet-card
  mode below the 900px crossover is unchanged, as are week navigation,
  scope/publisher filters, honest state chips (FRG-UI-047), the optimistic
  monitor toggle (FRG-UI-048), and the add-from-anywhere affordances
  (FRG-PULL-008).
- **Covers at shelf scale + on-row enrichment + publisher resolution**
  (MODIFIED `FRG-UI-042` — complete restatement): the cover-proxy
  rendering contract gains the shelf scale; creators and the clamped
  description surface on the row (full enrichment stays on the detail
  surface); and publisher tint/accent resolution normalizes corporate
  suffixes before the palette lookup, with a stable derived hue for
  publishers outside the named palette — fixing the live-data fallback
  defect everywhere the shared palette helpers are used.

## Capabilities

### Modified Capabilities

- `ui`: MODIFIED FRG-UI-018 (shelf rows replace agenda rows at/above the
  crossover); MODIFIED FRG-UI-042 (shelf-scale covers, on-row creators +
  clamped description, normalized publisher resolution).

## Impact

- Frontend only: `CalendarScreen.tsx` + its CSS module (row layout,
  chip, clamp), `theme/palettes.ts` (normalized lookup + derived hue —
  shared helpers, so library poster tints inherit the fix), vitest
  updates incl. the carried calendar-legibility refusal/measure tests
  adapted to shelf geometry. No backend, API, or schema change; no new
  dependency; no new attack surface (`docs/security/` untouched — the
  data rendered is the already-stored FRG-PULL-011 enrichment through the
  existing proxy).
- Manual: `docs/manual/user/web-ui.md` calendar section (row anatomy).
- e2e: the calendar-legibility browser-tier assertions (target floor,
  measure floor) carry over with shelf-adjusted density bounds.

## Non-goals

- Changing the below-crossover quiet cards, the day grouping, or any
  navigation/filter behavior.
- A user-facing density preference (compact/comfortable toggle) — one
  opinionated layout, revisit only if the shelf disappoints at scale.
- Publisher logos/marks — the chip is a swatch + name; imagery is a
  licensing/asset question deliberately avoided.

## Approval

**Approved by Adrian, 2026-07-30, in design session 2** — variant C
picked verbatim against the live-data comparison artifact
(https://claude.ai/code/artifact/3ca8df0f-b43d-40d9-899a-7209580bbfff):
"honestly, the shelf feels most comfortable … this greatly aids
discoverability. so C." The palette-normalization repair rides as the
bugfix half of the same decision.
