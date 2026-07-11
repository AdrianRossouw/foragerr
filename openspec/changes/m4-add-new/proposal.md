# m4-add-new

## Why

M4 chapter 4: the Add New screen is the last daily-use surface still on the
pre-refresh design, and it has one real behavioral wart — ComicVine lookup
results render in CV's raw `name:asc` alphabetical order, so searching "Saga"
buries the obvious match under alphabetically-earlier volumes. We already
compute plausibility signals (name similarity, year proximity, target-issue
sanity) per candidate but use them only as display chips; FRG-META-007
deliberately says "annotate, never auto-pick", so making the *ordering* smarter
is a spec-level decision, taken here explicitly rather than drifted into.

## What Changes

- **Redesign the Add New screen** to the design handoff (§3 add-new):
  expandable result cards (cover, name, year, publisher, issue count, deck,
  "In library" badge) opening an inline add-config panel — Root Folder +
  Format Profile selects, Monitor as segmented buttons, "Collect as"
  (Single Issues / Collected Editions), Cancel / Add primary. All existing
  functionality (URL/4050-id paste, autosuggest, error/truncated/empty states,
  no-root-folders empty state, search-on-add) is preserved.
- **Relevance ordering** (new FRG-META-015): lookup and suggest candidates are
  ordered by the existing plausibility signals (name similarity first, year
  proximity as tiebreak), server-side, identically for both endpoints. Ordering
  only — no candidate is dropped, no auto-pick; FRG-META-007's
  annotate-don't-decide contract is amended to say "annotate and order, never
  drop or pick".
- **Add-time booktype override** ("Collect as"): the add request accepts an
  optional explicit booktype that overrides FRG-SER-018's title-cue derivation;
  omitted = derive as today. Never affects wanted-suppression (FRG-SER-019
  invariant untouched — it has no booktype predicate).
- **README screenshot refresh** (FRG-PROC-017) since a shipped screen's
  appearance changes; manual "Adding a series" section rewritten.
- Housekeeping rider: fix the registry header's stale "Transmission" →
  qBittorrent (the FRG-TOR-002 spec has said qBittorrent all along; same
  staleness class as roadmap-single-source).

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `meta`: new FRG-META-015 (relevance ordering of lookup/suggest candidates);
  FRG-META-007 amended (annotate **and order**, never drop or auto-pick).
- `ui`: FRG-UI-005 amended (redesigned add screen per design handoff: result
  cards + inline add-config panel incl. Collect as).
- `ser`: FRG-SER-005/FRG-SER-018 scenario additions (add accepts explicit
  booktype override; derivation remains the default).

## Non-goals

- No new "quality profile" concept — the design's "Format Profile" select maps
  to the existing FRG-QUAL-001 entity as-is.
- No changes to release/download search (FRG-SRCH-*) — "search ranking" here
  means metadata *volume lookup* ordering only.
- No sort/filter controls on the results list (the ranked order is the order);
  add one later only if real use demands it.
- No publisher hard-filtering beyond the existing ignore list.

## Impact

- **Backend**: ordering applied in the lookup/suggest pipeline
  (`metadata/comicvine.py` / `api/series.py`); `SeriesCreate` gains optional
  `booktype`; `library/flows/add.py` honors it.
- **Frontend**: `screens/add/AddSeries.tsx` rebuilt to the design (existing
  hooks/API layer largely reusable); `AddSeries.test.tsx` reworked.
- **Docs**: `docs/manual/user/web-ui.md` §Adding a series; README tour assets
  via `tools/refresh-readme-shots.sh` if the add screen is in the shot set.
- **Registry**: allocate FRG-META-015; header Transmission fix.
- **Security**: no new attack surface — same CV endpoints, same untrusted-input
  handling (FRG-META-014); no docs/security update needed.
- **SOUP**: no dependency changes expected.

## Approval

Approved by Adrian 2026-07-11, in-session (AskUserQuestion: "Full scope") per
FRG-PROC-009 — redesign + FRG-META-015 relevance ordering (META-007
amendment) + add-time Collect-as override + screenshot/manual/registry riders.
