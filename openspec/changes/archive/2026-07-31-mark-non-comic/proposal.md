# mark-non-comic — the operator's own classification, sticky

## Why

Owner dogfood 2026-07-30: a "5th Edition Mega Bundle" put 73 items into
review — every one publisher-less, so the library-wide publisher rules
(FRG-SRC-012) can never fire on them, and the file-shape classifier
called the PDFs comics. The owner asked for "a 'mark as non-comic'
button… it doesn't need to be on a bundle level. the select bundle ->
<action> works fine." Today the only exits are Ignore (which means
withdrawal, not classification) or waiting for rules that cannot apply.
An operator's classification must also survive the next sync — the
write-back that re-derives classification for `new` rows would silently
reverse it.

## What Changes

- **Operator classification override** (new `FRG-SRC-016`): mark
  non-comic / mark comic, per row and in bulk (composing with the
  bundle/group/shift-range selection helpers), recorded with operator
  provenance (`classified_via`, migration 0033) that the sync write-back
  and publisher rules both honor — an operator-classified row never
  moves automatically, in either direction.
- MODIFIED `FRG-SRC-012`: the rules' reclassification scope carves out
  operator-classified rows.
- MODIFIED `FRG-SRC-004`: the operator action set gains classify.
- MODIFIED `FRG-UI-029`: bulk-bar marks beside accept/ignore/restore; the
  non-comic toggle shows its hidden count; the non-comic view offers the
  reverse mark.

## Capabilities

### New Capabilities

- `sources`: ADDED FRG-SRC-016.

### Modified Capabilities

- `sources`: MODIFIED FRG-SRC-012, FRG-SRC-004.
- `ui`: MODIFIED FRG-UI-029.

## Impact

- Backend: migration 0033 (`classified_via` nullable Text — the
  matched_via provenance pattern); sync gate adds the operator carve-out;
  single + bulk classify actions on the established per-row-outcome
  shape; resource exposes `classified_via`.
- Frontend: bulk-bar buttons + row action, hidden-count on the toggle,
  Mark-comic in the non-comic view.
- Manual: sources review section. No new attack surface (same
  authenticated bulk surface, additive column).

## Non-goals

- Bundle-level classification entities (owner: row-level via selection).
- Any change to Ignore semantics or the publisher rules themselves.
- Retro-classification of decided rows (matched/ignored refuse the mark;
  restore first — the house re-decision rule).

## Approval

Owner direction 2026-07-30 ("i think i would like a 'mark as non-comic'
button… row level"), plan confirmed same day ("nope. sounds good."),
carried by 2026-07-31 "approve and continue with the next items".
