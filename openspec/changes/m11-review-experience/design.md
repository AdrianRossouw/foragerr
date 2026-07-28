# m11-review-experience — design

## Context

Research (2026-07-28, two read-only maps) established: proposals are
library-first (`sources/matching.py` `compute_proposed_match`, lines
164-211) scored by a character-level `SequenceMatcher` ratio with no
token gate — the verified "Absolute Green Arrow at 0.327" mechanism; the
row picker is a library-only `<select>` (`EntitlementRow.tsx:187-207`);
the backend "pick any CV volume" seam already exists end-to-end
(`add_entitlement` takes `cv_volume_id`, degrades to match when
in-library, sweeps siblings — FRG-SRC-008); the AddSeries lookup surface
(`/api/v1/series/lookup` + `/lookup/suggest`, `useLookup`/`useSuggest`,
`have_it` marking) is directly reusable; the bundle display name
(`product.human_name`) is in every order payload and currently discarded
(`humble.py parse_order` reads only `subproducts`); classification is
pure format-shape (`sources/classify.py`) with the per-subproduct
`publisher` already captured and persisted; the review list renders all
rows flat and unvirtualized (`StoreManage.tsx:301-315`); bulk actions
are ignore/restore (+ single-series match) with a client-side accept
loop; `franchise_key` and `query_term` both bottom out in the one shared
`parser.normalize.matching_key()` fold.

## Goals / Non-Goals

**Goals:** CV is the matching universe with the library as overlay; no
review row is ever a dead end; the 1,318-row corpus is workable in
minutes (search, collapse, bundle bulk); RPG contamination is
operator-controllable; trade-shaped items propose collected editions.

**Non-Goals:** CV budget lanes/calibration/meter (change 3); any
import-time matching change; library-import screen; auto-sync posture
changes; multi-key CV.

## Decisions

**D1 — CV-first proposals with a token gate (FRG-SRC-010).**
`compute_proposed_match` inverts: candidates come from CV
(`suggest_series`, budget-aware exactly as today's deferral — a budget
hit still leaves the row un-proposed and retryable), and library
membership is an overlay computed by `cv_volume_id` lookup (the
`have_it` pattern), not a separate ranking pool. Scoring gains a
**token-overlap gate**: a candidate scores only if its folded key shares
at least one token with the folded query term (articles already dropped
by the fold); zero-overlap candidates are discarded before similarity
ranking, which kills the Absolute-Green-Arrow class outright. The
propose floor stays 0.5 *on gated candidates*; `AUTO_MATCH_THRESHOLD`
semantics are unchanged (auto-sync still requires ≥0.85 — and note the
FRG-PP-022 guard-3 backstop from change 1 already prevents auto-matched
ordinals from landing). "No plausible match" is a stored verdict, never
a terminal state: the resource says so and the UI always renders the
row search (D3). Library-only mode (no CV key configured) degrades to
today's library ranking — recorded in the spec as the explicit fallback.

**D2 — TPB routing as a re-rank, not a filter (FRG-SRC-010).**
A trade-shaped entitlement (its `human_name` carries a collected-edition
cue via the shared `booktype_cue_phrases` vocabulary — never a second
cue list) boosts CV candidates whose names carry the same cues, and
demotes bare singles lines, so "Saga Vol. 4" proposes the Saga TPB
volume. Boost/demote, never exclude — CV metadata carries no booktype
field, so name cues are the only signal and must stay soft. The
import-time trade guard (FRG-PP-022 guard 1) remains the backstop for a
mis-routed match.

**D3 — Per-row search is the AddSeries surface, mounted per row
(FRG-UI-039).** The row picker becomes a free-text search reusing
`useSuggest`/`useLookup` (debounce, min-3-chars, outcome notes,
`have_it`) rendered in an expandable row panel. Picking a `have_it`
candidate calls match; picking a new one calls add with explicit
`cv_volume_id` — both through the existing mutations, both stamping
`matched_via` operator explicitly (D7). The library `<select>` is
retired. The search affordance renders on EVERY reviewable row
regardless of proposal state (never-terminal, FRG-UI-029 restatement).

**D4 — Bundle identity is denormalized per row (FRG-SRC-011).**
`parse_order` reads `product.human_name`; migration 0026 adds nullable
`bundle_human_name` to `source_entitlements` (denormalized — rows
already carry `gamekey`, and a bundle's name is immutable order
metadata; no new table). Sync backfills it for existing rows on the
next run (upsert already keys by gamekey+machine_name; the field
updates like other display details per FRG-SRC-003's safe-resync rule).
`EntitlementResource` exposes it; the UI groups the bulk bar's
selection helpers by bundle ("select bundle") and shows the bundle name
on rows/groups.

**D5 — Apply-to-group rides the accept-proposals seam (FRG-SRC-011).**
The client-side accept loop (`acceptSelected`) moves server-side: a new
bulk action `accept` applies EACH row's own stored proposal in one
request (per-row transaction, per-row errors, exactly the `_bulk()`
idiom). "Apply match to group" is then: select group (bundle or
franchise collapse) → accept. Add-shaped groups converge via the
FRG-SRC-008 sweep (the first add re-resolves siblings to match
proposals; the loop's subsequent rows then match) — no new
apply-machinery is invented. Bulk bodies stay id-lists; per-bundle
targeting is a client-side selection concern (consistent with the
FRG-UI-025 shift-range pattern).

**D6 — Collapse and virtualization (FRG-UI-029 MODIFIED).**
Review rows group by `matching_key(query_term(human_name))` — the one
shared fold; groups with >N rows render collapsed with a count and
expand on demand (the 145-Spawn case). The list virtualizes with
`@tanstack/react-virtual` (new frontend runtime dep → SOUP row in this
change; chosen over react-window for its measurement-free dynamic-row
support and because TanStack Query is already the app's data layer
family). Grouping is computed client-side from the already-full
entitlement list response (no API change; the list endpoint already
returns everything in one response today — server pagination is
deliberately NOT introduced in this change, recorded as a non-goal so
scope holds).

**D7 — matched_via goes fail-closed (change-1 follow-up, adopted
here).** `matched_via` becomes a required keyword through
`match_entitlement`/`add_entitlement`/`_resolve_as_match`/`bulk_*`;
every API endpoint passes `MATCHED_VIA_OPERATOR` explicitly;
`enrich._auto_accept` stays the only `MATCHED_VIA_AUTO` caller. No
behavior change — the change is that an omission now fails loudly at
call time instead of silently minting operator provenance.

**D8 — Publisher rules are operator-owned and sticky-decision-safe
(FRG-SRC-012).** A per-source list of publisher names (settings JSON on
`SourceRow.settings`, same encrypted envelope — no new table) forces
matching items to `other` at classification time. Matching is on the
folded publisher string. Re-sync reclassifies ONLY rows still
`review_status="new"` whose classification came from the automatic
classifier — matched/ignored rows never move (the sticky-decision rule
FRG-SRC-004 already establishes). The list ships EMPTY; the UI offers a
one-click "suggested starter list" (RPG publishers observed in the
dogfood corpus) that the operator applies deliberately — never
pre-applied (intent-presuming-defaults rule, owner 2026-07-11).

## Risks / Trade-offs

- [CV-first enrichment spends budget on every new entitlement at
  first-sync scale] → the existing deferral semantics are preserved
  verbatim (budget hit → skip CV, stay retryable, resume next sync);
  change 3's lanes/calibration then govern the profile. Recorded
  explicitly so change 3 knows the consumer.
- [Token gate could exclude a legitimately-renamed volume (zero shared
  tokens with the store title)] → the row search is always present; the
  gate governs only automatic proposals, and the never-terminal rule
  makes the residual cost one manual search.
- [Client-side grouping at 1,318 rows on each render] → the fold is
  string ops; memoized by list identity; virtualization bounds DOM cost.
  If a future corpus is 10× this, server grouping becomes its own
  change.
- [New frontend dep (react-virtual)] → SOUP-registered, MIT, tiny;
  alternative (hand-rolled windowing) rejected as the classic
  scroll-jank tarpit.
- [Publisher-rule folding false positives (e.g. a comic imprint sharing
  a name)] → rules are per-source, operator-edited, and reclassification
  never touches decided rows; the review filter still shows Other rows
  (nothing is hidden or deleted).

## Migration Plan

Migration 0026: nullable `bundle_human_name` TEXT on
`source_entitlements`; backfilled by the next sync (no data rewrite in
the migration itself). Frontend dep addition registered in SOUP. No
other schema change; rollback = revert tag (column inert to older
code).

## Open Questions

None blocking. Numbers chosen at implementation and pinned by tests:
the collapse threshold N (default: groups of ≥3 collapse) and the
starter publisher list contents (from the dogfood corpus, offered not
applied).
