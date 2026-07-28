# m11-source-import-trust — provenance-authoritative source imports

## Why

Live dogfood against a real 1,318-item Humble collection (test-rig findings
#9, #10, #12, #15, #21) showed the import pipeline discarding knowledge it
already holds: a file arriving from an entitlement the operator explicitly
matched to a series still fails with "could not match this file to a known
series and issue" because the grab-history short-circuit demands an issue id
store grabs never have; Humble's `Vol. N`-means-issue-N naming defeats the
parser; acting on one review row strands its siblings with stale proposals
that 400 on the next click; manually importing a blocked source download
leaves the queue row and entitlement state stale forever; and a failed
source download is invisible outside the Sources screen, with a retry
action the sources spec promises (FRG-SRC-006) but the product never built.

## What Changes

- **Provenance-authoritative series resolution** (new `FRG-PP-021`): a
  completed download whose grab history carries a series hint without an
  issue id (the store-grab shape) resolves against that series
  authoritatively — only the issue number is derived from parse evidence.
  Resolution never falls through past a known provenance series to
  unscoped filename matching.
- **Ordinal-fallback issue resolution** (new `FRG-PP-022`): when the
  target series is explicitly known and evidence yields no issue but does
  yield an ordinal volume (`Vol. N`), issue N is tried against that
  series' real issue index. Handles both mislabeled singles
  (SPAWN Vol. 243 → #243) and true trades (Saga Vol. 4 → TPB issue 4)
  because the operator-chosen series disambiguates; a miss stays blocked.
- **Issue-word filler stripping + Humble corpus rows** (new
  `FRG-IMP-026`): bare "Issue"/"Issues" filler preceding an issue number
  no longer leaks into the parsed series title
  ("Strangelands Issues #8" → series "Strangelands"); additive corpus
  rows pin the Humble idioms (`Vol. N` singles, `Issue # N`, `Issues #N`).
- **Review-proposal freshness** (new `FRG-SRC-008`): the add action on an
  entitlement whose proposed ComicVine volume is already in the library
  degrades to match-to-existing instead of failing 400; a successful add
  re-resolves sibling entitlements' proposals that pointed at the same
  volume into match proposals against the new series.
- **Failed source-download visibility** (new `FRG-SRC-009`): an explicit
  retry action on a failed entitlement download (endpoint + row
  affordance) and a health warning when source downloads sit failed —
  today `_sources_component` never looks at `download_state`.
- **Manual-import state mirror** (MODIFIED `FRG-PP-016`): download-scoped
  manual import applies the terminal state to the tracked-download row
  (and emits the queue event) instead of leaving it `import_blocked`
  forever.
- **Source entitlement mirror on manual import** (MODIFIED `FRG-SRC-006`):
  manually importing a source download transitions the entitlement's
  download state and runs owned-via-edition reconciliation, exactly as the
  automatic drain does; the promised retry action moves to `FRG-SRC-009`
  as a real requirement.

## Capabilities

### New Capabilities

None — every change extends an existing capability area.

### Modified Capabilities

- `pp`: ADDED `FRG-PP-021` (provenance-authoritative series resolution),
  ADDED `FRG-PP-022` (ordinal-fallback issue resolution under a known
  series), MODIFIED `FRG-PP-016` (manual import applies tracked-download
  terminal state; complete scenario restatement).
- `imp`: ADDED `FRG-IMP-026` (issue-word filler stripping; Humble idiom
  corpus rows under the FRG-IMP-021 additive-only rule).
- `sources`: ADDED `FRG-SRC-008` (review-proposal freshness), ADDED
  `FRG-SRC-009` (failed source-download retry + health visibility),
  MODIFIED `FRG-SRC-006` (manual-import entitlement mirror; retry moves
  to FRG-SRC-009; complete scenario restatement).

## Impact

- Backend: `importer/pipeline.py` (`_reconcile_base` steps 2–3),
  `importer/evidence.py` (consumed as-is), `parser/` (filler stripping) +
  `tests/parser/corpus.py` (additive rows, count assert),
  `sources/review.py` (add-degrade, sibling re-resolution),
  `downloads/manual_import.py` (state application + source mirror via
  `apply_source_import`), `health/service.py` (`_sources_component`),
  `api/sources.py` (retry endpoint).
- Frontend: `screens/sources/EntitlementRow.tsx` (retry button on failed
  rows), source hooks.
- API: one new authenticated endpoint
  (`POST /sources/entitlements/{id}/retry-download`); no new listener, no
  new parser of untrusted input, no new outbound integration — the retry
  re-queues the existing grab task under existing auth. **No new attack
  surface; no docs/security update required** (per FRG-PROC-006 this is
  the recorded rationale).
- Manual impact (FRG-PROC-011): `docs/manual/` sources section — retry
  affordance, failure visibility/health warning, add-degrades-to-match
  review behavior; import section — Humble naming idioms now resolve.
- No migration; no dependency change (SOUP register untouched).

## Non-goals

- Full Queue/Activity unification of source downloads (retry + health
  minimum only; pre-design records the larger surface for later).
- Any change to the one-directional subset matcher's semantics for
  unscoped files (the asymmetry that protects "Batman" vs "Batman
  Beyond" stands).
- Review-experience features (CV-search picker, bulk actions, grouping —
  change 2), CV budget behavior (change 3), classification rules
  (change 2).
- Trade/format semantics beyond the ordinal fallback
  (format-preference direction owns grab/keep/serve).
- Remote path mappings (M11 change 4 owns path-visibility health).

## Approval

Proposed under the **M11 standing grant** (owner approval 2026-07-27,
recorded in the m11-import-intelligence pre-design's Approval section on
branch `change/m11-import-intelligence`, commit 562b16f): M11 implementing
changes proceed autonomously with full tiered gates + Codex + e2e + live
rig verification per change, hard stop at milestone close. This proposal
cites that grant as its FRG-PROC-009 approval; no intent-presuming
defaults are introduced (every new behavior either honors an explicit
operator choice or surfaces state — none guesses intent).
