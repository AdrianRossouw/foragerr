# publisher-filtering — non-comic filtering that works out of the box, in one place

## Why

Owner dogfood feedback 2026-07-29 on the shipped per-source publisher
rules (FRG-SRC-012):

- **It ships empty**, so it does nothing until the operator types
  publishers in — another first-install setup chore on a screen that
  already has many. "It just creates setup tasks the user has to do."
- **It lives per-source on the Sources screen**, while the *sibling*
  control — the ComicVine ignore list (FRG-META-020) — lives in Settings
  and ships prepopulated. Two publisher-filtering controls, two places,
  two behaviors, is the actual confusion.
- **Its UI language leaks implementation context**: the help text reads
  "the RPG-sourcebook escape hatch." A user should not see "escape hatch,"
  and RPG books are not the only non-comic content — tech/textbook
  publishers (O'Reilly, No Starch, Manning, Packt) are a whole other class
  ("I don't buy textbooks, but others might").

The through-line: non-comic filtering should **work by default, in one
obvious place, in plain language** — not be an empty, oddly-placed,
jargon-labelled setup task.

## What Changes

- **Publisher classification rules become a single library-wide list in
  Settings** (MODIFIED `FRG-SRC-012` — complete restatement): the
  per-source rule list is replaced by one operator-managed list that
  applies across sources, living beside the ComicVine ignore list in
  Settings (not on the Sources screen). Existing per-source rules migrate
  into it.
- **It ships with curated defaults** (part of MODIFIED `FRG-SRC-012`):
  a conservative, unambiguous set of **non-comic publisher houses** —
  RPG/game publishers (Paizo, Pelgrane, etc.) and tech/textbook
  publishers (O'Reilly, No Starch, Manning, Packt, etc.) — so a fresh
  install filters the common non-comic bundle content with no setup. Every
  default is **operator-removable** ("others might buy them"), and the
  same recoverable-visibility rule applies (nothing is dropped; reclassified
  items are retained and hideable, FRG-UI-032-style). Publishers of
  genuine comics are deliberately excluded from the defaults, same posture
  as the curated CV ignore list (FRG-META-020).
- **Plain-language UI** (new `FRG-UI-046`): the Settings panel describes
  the feature in user terms — "Some things in a bundle aren't comics —
  RPG rulebooks, tech-book PDFs, art books. List their publishers here and
  foragerr files them as Other, whatever the file type." No "escape
  hatch," no "RPG-sourcebook" as the sole framing.

## Capabilities

### New Capabilities

None — extensions of existing areas.

### Modified Capabilities

- `sources`: MODIFIED FRG-SRC-012 (library-wide list, curated removable
  defaults, Settings home; complete restatement).
- `ui`: ADDED FRG-UI-046 (Settings publisher-filtering panel, plain
  language, default set editable). The old per-source Sources-screen panel
  is removed.

## Impact

- Backend: move the rule store from the per-source settings envelope to a
  library-wide config value (a `DEFAULT_NON_COMIC_PUBLISHERS` seed
  mirroring `DEFAULT_IGNORED_PUBLISHERS`'s shape/`*`-substring semantics);
  `sources/classify.py` reads the library-wide list instead of per-source;
  `api/sources.py` publisher-rules PATCH → a config resource; migration to
  carry any existing per-source `publisher_rules` into the new list.
- Frontend: remove `PublisherRules.tsx` from `StoreManage`; add the panel
  to Settings beside the CV ignore-list control; plain copy.
- Intent-presuming default (2026-07-11 rule): shipping a non-empty default
  filter changes classification on fresh installs. Called out for owner
  sign-off — the owner explicitly asked for defaults that exclude most
  non-comic content by default, and every default is removable and
  non-destructive (retained + recoverable, never dropped).
- No new attack surface; no new dependency. Manual: `docs/manual/`
  settings + sources pages (the control moved; what the defaults do).

## Non-goals

- Deeper classification from Humble item metadata (finding #7) — a bigger
  classifier change; publisher rules stay the publisher-level lever.
- Merging with the ComicVine *search* ignore list (FRG-META-020) into one
  control — they act at different points (CV search vs. source
  classification); co-locating them in Settings is enough. A future unify
  is possible but out of scope.
- Per-source overrides — the owner's model is one library-wide list;
  per-source granularity is dropped, not re-added under Settings.

## Approval

Owner-directed 2026-07-29 ("merged into settings, and defaults that
exclude most non-comic things by default … otherwise it just creates
setup tasks"). Awaiting formal approval (FRG-PROC-009) — this reverses
FRG-SRC-012's "ship empty / suggestions opt-in" stance, so it wants an
explicit yes before implementation.
