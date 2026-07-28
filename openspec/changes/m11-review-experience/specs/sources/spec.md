# sources — delta for m11-review-experience

## ADDED Requirements

### Requirement: FRG-SRC-010 — ComicVine-first honest proposals

The system SHALL compute entitlement match proposals against ComicVine's
catalog as the matching universe, with the operator's library as an
overlay, not a ranking pool: a proposed ComicVine volume already present
as a library series is proposed as a direct match to that series, and one
not present is proposed as an add — either way a single operator action
resolves the row. Automatic proposals SHALL pass a token-overlap gate
and a minimum confidence floor, both computed over titles stripped of
edition boilerplate (volume/book/part/issue designators, bare ordinals,
and collected-edition cue words — via the shared vocabularies, never a
second list): a candidate sharing no substantive token with the query is
never proposed whatever its character-level similarity, boilerplate
overlap alone can neither admit a candidate nor lift one over the
auto-accept threshold, and the floor SHALL NOT discard a candidate whose
stripped canonical title is contained by the stripped query (a store
title's subtitle decoration never buries the exact-titled volume). A row
that clears neither gate nor floor carries an explicit "no plausible
automatic match" verdict that is never terminal — the operator search
(FRG-UI-039) remains available on every reviewable row. Trade-shaped
entitlements (collected-edition cues OR a volume/book-ordinal shape in
the store title) SHALL prefer collected-edition-shaped ComicVine
candidates in ranking — a soft re-rank, never a filter. When no
ComicVine key is configured, proposal computation SHALL degrade to
library-only ranking and say so. Budget exhaustion SHALL leave affected
rows un-proposed and retryable exactly as before (deferral semantics
unchanged, FRG-META-016).

#### Scenario: Zero-token-overlap titles are never proposed

- **WHEN** proposals are computed for an entitlement whose folded store
  title shares no substantive token with a candidate's folded title
- **THEN** that candidate is not proposed at any similarity score (the
  "Absolute Green Arrow for Something is Killing the Children" class is
  impossible), and a row with no gated candidate above the floor carries
  the explicit no-plausible-match verdict

#### Scenario: Boilerplate overlap is not identity evidence

- **WHEN** two different series share only edition boilerplate (e.g.
  "Saga Vol. 1" vs a candidate "Batman Vol. 1", or near-twins like
  "The Boys Vol. 1" vs "The Bots Vol. 1")
- **THEN** the boilerplate neither admits the candidate through the gate
  nor inflates its confidence toward the auto-accept threshold — scoring
  runs on the stripped titles

#### Scenario: The exact-titled volume survives a decorated store title

- **WHEN** the store title carries edition decoration and a subtitle
  ("Hellboy Omnibus Volume 1: Seed of Destruction") and ComicVine's
  candidates include the exact-titled volume ("Hellboy")
- **THEN** the exact-titled volume is never floored out by
  length-asymmetric similarity — containment of the stripped canonical
  title in the stripped query keeps it proposable

#### Scenario: In-library ComicVine candidate proposes a match, not an add

- **WHEN** the best ComicVine candidate for a new entitlement is a volume
  already present as a library series
- **THEN** the proposal is a match to that series, and accepting it
  performs the match in one action

#### Scenario: Trade-shaped entitlement prefers the collected edition

- **WHEN** proposals are computed for an entitlement whose store title
  carries a collected-edition cue and ComicVine offers both a singles
  line and a collected-edition volume of that title
- **THEN** the collected-edition volume ranks first; the singles line
  remains available among candidates (re-rank, not filter)

#### Scenario: No key degrades honestly

- **WHEN** proposals are computed with no ComicVine key configured
- **THEN** ranking falls back to library-only and the proposal records
  that ComicVine was unavailable rather than presenting the fallback as
  a catalog verdict

### Requirement: FRG-SRC-011 — Bundle identity, group actions, and accept-in-bulk

The system SHALL capture each order's bundle display name during sync and
carry it on every entitlement row, and SHALL support acting on the review
queue in groups: a server-side bulk accept that applies each selected
row's own stored proposal (per-row transactions, per-row errors — never
one shared target forced across heterogeneous rows), bulk ignore/restore
as today, and selection helpers scoped by bundle and by collapse group
(FRG-UI-029). Applying a match to a group of same-title rows SHALL
converge through the FRG-SRC-008 sibling re-resolution (the first add
converts the siblings' proposals to matches; the remaining accepts match)
— one mechanism, no parallel apply-machinery.

#### Scenario: Bundle name captured and carried

- **WHEN** a sync ingests an order whose payload names its bundle
- **THEN** every entitlement row from that order carries the bundle
  display name, existing rows gain it on their next sync, and the review
  UI can select a whole bundle by it

#### Scenario: Bulk accept applies each row's own proposal

- **WHEN** the operator bulk-accepts a selection whose rows propose
  different targets (some matches, some adds)
- **THEN** each row is resolved per its own proposal in its own
  transaction, failures are reported per row without aborting the rest,
  and no row is forced to another row's target

#### Scenario: Same-title group converges via one add

- **WHEN** the operator bulk-accepts a collapsed group whose rows all
  propose the same not-yet-in-library ComicVine volume
- **THEN** the first accept adds the series, sibling proposals re-resolve
  to matches (FRG-SRC-008), and the remaining accepts match into the new
  series with no "already in the library" error

### Requirement: FRG-SRC-012 — Publisher classification rules

The system SHALL support per-source, operator-managed publisher rules
that classify matching items as non-comic at sync time, matched on the
folded publisher string. Rule changes SHALL reclassify only rows still in
the automatic classifier's hands (review state `new`); matched and
ignored rows never move. The rule list SHALL ship empty; any suggested
starter content is offered as an explicit operator action, never
pre-applied. Reclassified items follow the existing non-comic visibility
rules (retained, hidden by default, never dropped).

#### Scenario: Publisher rule reclassifies unreviewed rows

- **WHEN** the operator adds a publisher to the rule list and the next
  sync runs
- **THEN** `new` items from that publisher are classified `other` (newly
  synced and previously synced alike), and previously matched or ignored
  items are untouched

#### Scenario: Rules ship empty and suggestions are opt-in

- **WHEN** a source is connected with default settings
- **THEN** the publisher rule list is empty and no suggestion is applied
  without the operator explicitly accepting it

## MODIFIED Requirements

### Requirement: FRG-SRC-003 — entitlement sync

The system SHALL discover owned items by polling the Humble order API on a schedule
(default daily) and on operator demand ("Sync now"), diffing by store-native key
(gamekey + subproduct identity) so re-syncs are idempotent. Sync SHALL capture the
order's bundle display name alongside per-item display details (FRG-SRC-011). Items
SHALL be classified comic/other by the format-shape classifier combined with the
operator's publisher rules (FRG-SRC-012); non-comic items SHALL be retained and
visible on demand, never silently dropped. A sync failure SHALL never crash the
scheduler; malformed order entries are skipped and logged, and partial results are
kept.

#### Scenario: New purchase appears

- **WHEN** a sync runs after the operator buys a bundle containing comics
- **THEN** each new comic item appears exactly once as a `new` entitlement with title, format, bundle name, and a proposed match per FRG-SRC-010, and a subsequent sync creates no duplicates

#### Scenario: Non-comic items discoverable

- **WHEN** a synced bundle contains games and books alongside comics
- **THEN** the non-comic items exist as `other`-classified entitlements, hidden by default and listed when the operator shows them

### Requirement: FRG-SRC-004 — review-first entitlement workflow

The system SHALL hold each newly discovered comic entitlement in a review state
(`new`) with a server-proposed match computed against the ComicVine catalog
(FRG-SRC-010), supporting operator actions: match to an existing
series/collection, add as new, pick any ComicVine volume via search
(FRG-UI-039), ignore, and restore, individually and in bulk
(FRG-SRC-011). By default nothing SHALL download without an operator accept
action. A per-source auto-sync toggle MAY automate accept-and-download for
confidently matched new items and SHALL default to OFF. Operator actions
SHALL record operator provenance explicitly at the API boundary
(matched-via, required — never inherited from a default), with auto-sync
the sole automatic-provenance writer.

#### Scenario: Default requires operator action

- **WHEN** a sync discovers new comic entitlements on a source with default settings
- **THEN** no download or library mutation occurs until the operator acts on each item (or bulk-accepts)

#### Scenario: Auto-sync is opt-in

- **WHEN** the operator enables the auto-sync toggle and a sync later finds a confidently matched new item
- **THEN** that item is accepted and downloaded automatically with automatic provenance recorded (its import honors the FRG-PP-022 operator-only guard), and items below the confidence threshold remain in review

#### Scenario: Ignore and restore

- **WHEN** the operator ignores an entitlement and later restores it
- **THEN** ignored items are excluded from pending-review counts and default views but remain listed under their filter; restore returns the item to `new` with its proposed match recomputed

#### Scenario: Ignore cancels in-flight acquisition

- **WHEN** the operator ignores an accepted entitlement whose download has not yet durably imported (queued, fetching, verifying, or awaiting/undergoing import)
- **THEN** nothing lands in the library for it — the grab aborts at its re-read guard or the completed download is withdrawn before any file moves — and a later restore + re-accept downloads afresh
