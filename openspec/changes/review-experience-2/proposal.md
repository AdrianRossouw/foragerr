# review-experience-2 — duplicate-aware review, a picker that can tell editions apart, and groups that group

## Why

Three rig findings from live review of a real store account (2026-07-29):

- **Byte-identical duplicates review twice and import never.** The same
  volume bought in two bundles arrives as two entitlements with the same
  md5. foragerr keys entitlements per-(bundle, item) and treats md5 as
  integrity-only, so review shows two rows per book. Worse than doubled
  review work: accepting one leaves the twin re-proposed as a fresh
  `new` row, and accepting *that* downloads a byte-identical file the
  importer then refuses (`import_blocked`, equal size loses the
  larger-size constraint) — 2× rows, 2× bandwidth, and a terminal state
  with no explanation that the operator already owns this exact file.
- **The match picker can't distinguish a collected edition from
  singles.** Candidates show publisher/year/issue-count, but nothing
  marks a volume whose title reads as a trade collection, so picking the
  right CV volume for "Vol. 2" cases is guesswork. Also, the picker's
  input *advertises* pasting a ComicVine URL/id and normalizes it — then
  submits it as a name search, which returns nothing. The id-resolution
  endpoint (FRG-API-026) exists; its only consumer is the Calendar add
  flow.
- **One series under two names doesn't group, and groups aren't
  sorted.** "Series Vol. 3" and "THE FIRST ADVENTURE OF SERIES" fold to
  different group keys, so one franchise reviews as scattered groups;
  within a group, rows render in sync-discovery order rather than
  volume/issue order.

## What Changes

- **md5-identical entitlements become one reviewable unit** (new
  `FRG-SRC-015`): sync links same-source entitlements sharing a stored
  md5 into a duplicate set with one canonical row; the copies move to a
  new `duplicate` review state — excluded from pending counts, hidden
  behind a filter (retained and restorable, never dropped), never
  grabbed. Review once, import once. A one-time backfill links existing
  all-still-`new` sets on upgrade.
- **The review-state vocabulary gains `duplicate`** (MODIFIED
  `FRG-SRC-004` — complete restatement): restore extends to duplicate
  rows (unlinking them back to independent `new` review); decided rows
  are never re-linked.
- **The picker shows a collected-edition cue and honors a pasted id**
  (MODIFIED `FRG-UI-039` — complete restatement): candidates carry a
  soft "collected-edition title cues" badge derived from the one shared
  booktype vocabulary (ComicVine has no booktype field — the cue is
  honest about being a title heuristic), and a pasted CV volume URL/id
  resolves through the existing volume-id lookup (FRG-API-026) instead
  of dying as a name search. The group-header picker (FRG-UI-043)
  inherits both by construction.
- **Read-side group merge by title containment + within-group order**
  (MODIFIED `FRG-UI-029` — complete restatement): groups whose stripped
  keys are containment-related (one key's tokens a contiguous run inside
  the other — the same rule FRG-SRC-010 already applies at the
  confidence floor) merge for display, and group members render in
  volume/issue order from a server-computed sort key (single-fold rule:
  the parser derives it, the client never re-parses). The write-side
  sweep key (FRG-SRC-014) is deliberately unchanged.

## Capabilities

### New Capabilities

- `sources`: ADDED FRG-SRC-015 — md5-identical entitlement dedupe.

### Modified Capabilities

- `sources`: MODIFIED FRG-SRC-004 (review-state vocabulary gains
  `duplicate`; restore covers it).
- `ui`: MODIFIED FRG-UI-029 (duplicate-set presentation, containment
  display merge, within-group volume/issue order); MODIFIED FRG-UI-039
  (collected-edition cue, id-paste resolution).

## Impact

- Backend: migration 0032 (`duplicate_of` column + `(source_id, md5)`
  index); sync-time linking + startup backfill; grab/count/filter
  guards for the `duplicate` state; restore extended; candidate
  resources gain the derived collected-cues flag; entitlement resource
  gains the parsed sort key; listing gains the containment merge.
- Frontend: duplicate badge/filter on the review list; picker badge +
  id-path wiring (reuses the existing volume-id hook); group sort;
  merged-group labeling.
- No new attack surface: no new listener, no new parser of untrusted
  input (md5 values are already parsed/stored by entitlement sync;
  the id path reuses the existing authenticated FRG-API-026 endpoint;
  the cue derivation reuses the existing booktype vocabulary on data
  already held). No dependency changes; SOUP register untouched.
- Manual impact: `docs/manual/user/sources.md` review-workflow section
  (duplicate handling, the new filter, group order, picker cue and
  id paste). No README labelling change.

## Non-goals

- Cross-*source* dedupe (only same-source sets; a second store
  integration would revisit).
- Hash-based duplicate detection in the importer for library files
  (importer arbitration stays size/format-based; the store-provided md5
  is used pre-grab only).
- Changing the write-side sweep fold (FRG-SRC-014) or the confidence
  floor (FRG-SRC-010) — the containment merge is presentation-scoped by
  design (see design.md D4).
- CV metadata booktype (ComicVine exposes none; the cue stays a soft
  title heuristic, never a gate).

## Approval

Owner go recorded 2026-07-30: "do everything but the release pipeline
now" — the owner's direction on the queued dogfood changes, given with
the finding set already reviewed on the rig (Revival duplicate pairs,
Luther Strode grouping) and covering this write-up ahead of its
authoring, standing-grant style. The owner reviews the shipped result at
release; anything mis-scoped reverts per normal change control.
