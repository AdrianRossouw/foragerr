# m11-review-experience — ComicVine is the matching universe

## Why

The live rig's 1,318-item review queue exposed the review experience as the
milestone's bottleneck (findings #7, #8, #9, #11): proposals rank against the
operator's tiny library with a character-level similarity that let
"Something is Killing the Children Vol. 8" propose "Absolute Green Arrow" at
0.327; a row's only picker is a library-series dropdown, so the correct answer
is often unreachable ("not something i want to do 1000 times"); 145 Spawn
entitlements render as 145 flat rows; RPG sourcebooks contaminate the comic
bucket; and trade-shaped items propose singles volumes. The owner's direction
(2026-07-27, recorded in the pre-design): ComicVine is the matching universe —
the library is a shortcut overlay, and no review row is ever a dead end.

## What Changes

- **CV-first proposal computation** (new FRG-SRC-010): compute_proposed_match
  ranks against ComicVine's catalog; library membership becomes an overlay
  (an in-library candidate links directly; one not in the library
  adds-and-matches in one action — the FRG-SRC-008 seam). A token-overlap
  gate + minimum-confidence floor make proposals honest; "no plausible
  match" describes only the automatic verdict and always sits beside the
  live search. Trade-shaped entitlements prefer collected-edition CV
  volumes in ranking (review-time complement to FRG-PP-022's import-time
  guards).
- **Free-text CV search on every review row** (new FRG-UI-039): the
  AddSeries lookup UX (debounced suggest + full search, have_it overlay,
  outcome notes) mounted per row; picking a result matches (in library) or
  adds-and-matches (not in library) via the existing add path with an
  explicit operator provenance stamp.
- **Bundle identity + scale tools** (new FRG-SRC-011): sync captures the
  order's bundle display name (product.human_name — parsed today, discarded);
  review rows carry it; bulk actions gain per-bundle/order targeting
  (select-bundle → ignore/restore) and apply-match-to-group; review rows
  collapse by the shared matching-key fold (franchise/volume groups, 145
  Spawn rows → one expandable group).
- **Publisher classification rules** (new FRG-SRC-012): a per-source
  publisher rule list forces known non-comic publishers to Other at sync
  and reclassifies existing unreviewed rows on the next sync; operator
  decisions are never reclassified.
- **Thousand-row rendering** (MODIFIED FRG-UI-029): the review list
  virtualizes; the at-scale scenario is restated at the real corpus size.
- **matched_via fail-closed threading** (change-1 recorded follow-up):
  required keyword on the review chain, asserted explicitly at API
  boundaries.

## Capabilities

### New Capabilities

None — all changes extend existing capability areas.

### Modified Capabilities

- `sources`: ADDED FRG-SRC-010 (CV-first honest proposals + TPB routing),
  FRG-SRC-011 (bundle identity, per-bundle bulk, apply-match-to-group,
  review grouping), FRG-SRC-012 (publisher classification rules);
  MODIFIED FRG-SRC-003 (sync captures bundle name; classification gains
  publisher rules + reclassification semantics; complete restatement),
  MODIFIED FRG-SRC-004 (proposal mechanism language + auto-sync scenario
  restated for the CV universe; complete restatement).
- `ui`: ADDED FRG-UI-039 (per-row CV search picker); MODIFIED FRG-UI-029
  (review screen: collapse, bundle grouping/bulk, virtualized scale
  scenario at 1,318 rows, never-terminal rows; complete restatement).
- `meta`: no requirement change intended — per-row search reuses
  FRG-META-007/015 endpoints and ordering; FRG-META-016's budget governs
  the added traffic (change 3 owns lanes/calibration). If scoring needs a
  shared-ordering amendment it lands as MODIFIED FRG-META-015 with
  complete restatement (decided at design).

## Impact

- Backend: sources/matching.py (CV-first + token gate + floor + TPB
  preference), sources/humble.py + service.py (+ migration: bundle name
  column), sources/classify.py (+ publisher rules + reclassify pass),
  sources/review.py (bulk per-bundle, apply-match-to-group, matched_via
  threading), api/sources.py (bulk body, resource fields, publisher-rule
  settings surface).
- Frontend: screens/sources/* (virtualized grouped list, row search
  picker, bundle bulk bar), api hooks.
- DB: one migration (bundle display name on source_entitlements; publisher
  rules storage — settings JSON vs table decided at design).
- CV traffic: per-row search is operator-initiated and rides the existing
  FRG-META-016 budget; enrichment's batch profile changes (CV-first) is
  budget-shaped at design time with change 3's lanes in mind.
- Manual impact (FRG-PROC-011): docs/manual/user/sources.md (review
  workflow, search picker, bundles, publisher rules), web-ui.md if nav
  changes.
- Security: no new attack surface — no new listener, no new parser of
  untrusted input beyond fields already parsed from the authenticated
  Humble session (bundle display name string, sanitized like publisher);
  no new outbound integration (CV client reused). SOUP: no dependency
  change expected unless virtualization needs a library (decided at
  design; if added, register row in same change).

## Non-goals

- CV budget lanes/calibration/meter (change 3).
- Any change to import-time matching (change 1 owns it; FRG-PP-021/022
  stand).
- Multi-key ComicVine anything.
- Read-only sources; format preference semantics.
- Library-import screen changes (its CV flow already exists; only the
  sources review screen is in scope).

## Approval

Proposed under the M11 standing grant (owner approval 2026-07-27, recorded
in the m11-import-intelligence pre-design's Approval section, commit
562b16f): implementing changes proceed autonomously with full tiered
gates + Codex + e2e + live-rig verification, hard stop at milestone
close. The CV-is-the-matching-universe direction and the never-terminal
rule are the owner's own 2026-07-27 corrections, honored as written. No
intent-presuming defaults: auto-sync's opt-in posture is unchanged;
publisher rules ship EMPTY by default (populating them is an operator
action; a suggested starter list is offered in the UI, never pre-applied).
