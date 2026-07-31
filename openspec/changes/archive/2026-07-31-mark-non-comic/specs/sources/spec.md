# sources — delta for mark-non-comic

## ADDED Requirements

### Requirement: FRG-SRC-016 — Operator classification override

The system SHALL let the operator classify an entitlement row directly —
mark as non-comic, or mark as comic — individually and in bulk, recording
operator provenance on the classification. An operator-classified row
SHALL never be reclassified by the automatic classifier or by publisher
rules, in either direction, regardless of review state: the sync
write-back that re-derives classification for `new` rows skips
operator-classified rows. The override is available on any reviewable
row (the selection helpers — bundle, group, shift-range — compose with
it), takes effect immediately on the review surface, and follows the
existing non-comic visibility rules (retained, hidden by default under
the non-comic toggle, never dropped). Marking a matched, ignored, or parked-duplicate row
is refused the same way other re-decisions are — restore first.
Confirming a classification the automatic classifier already reached
SHALL NOT seize the row from the rules: provenance is recorded only when
the operator's decision differs from what the row already carries
automatically. A non-comic row SHALL NOT participate in md5 duplicate
linking (FRG-SRC-015) — dedupe exists to spare double review of comics —
and a parked copy that becomes non-comic leaves its set.

- **Milestone**: B (mark-non-comic).
- **Source**: owner dogfood 2026-07-30 — a store bundle of 73 items with
  no publisher field classified as comics by file shape; publisher rules
  (FRG-SRC-012) cannot fire without a publisher, and the operator's
  correction must not be silently reversed by the next sync.
- **Notes**: Provenance is a nullable `classified_via` column
  (`operator` vs NULL/automatic — the matched_via pattern), so an
  operator decision is distinguishable from the classifier's output and
  the sync gate can honor it. The publisher-rules lever stays the
  automatic path; this is the manual one.

#### Scenario: Marked non-comic sticks across syncs

- **WHEN** the operator marks a `new` comic-classified row (one with no
  publisher, say) as non-comic and the next sync runs
- **THEN** the row is classified `other` with operator provenance, hides
  under the non-comic toggle like any other non-comic row, and the sync
  leaves its classification untouched — as does any later publisher-rule
  change

#### Scenario: Bulk mark over a bundle selection

- **WHEN** the operator selects a whole bundle's rows and bulk-marks
  them non-comic
- **THEN** every selected `new` row is reclassified with operator
  provenance in one request with per-row outcomes, and rows that cannot
  be marked (matched/ignored) report their reasons per row

#### Scenario: A row marked comic is fully acquirable

- **WHEN** the operator marks a row the shape classifier had called
  non-comic (a PDF-only item, say) as comic, and accepts it
- **THEN** the row carries the file identity acquisition needs (its
  preferred format and checksum), grabs like any comic row, and a later
  sync neither re-nulls that identity nor reclassifies the row

#### Scenario: The reverse mark is symmetric

- **WHEN** the operator marks an operator-classified non-comic row back
  as comic
- **THEN** the row returns to the comic scope with operator provenance
  (still never auto-reclassified), and its proposal machinery treats it
  like any comic-classified `new` row

## MODIFIED Requirements

### Requirement: FRG-SRC-012 — Publisher classification rules

The system SHALL support an operator-managed, **library-wide** publisher
rule list that classifies matching items as non-comic at sync time,
matched on the folded publisher string (an entry ending in `*` matches as
a case-insensitive substring; every other entry matches exactly — the
trailing-`*` convention shared with the ComicVine ignore list,
FRG-META-020, though the two folds differ: classification folds with the
matching key, the ignore list casefolds, and only a **trailing** `*`
widens a classification rule). The list SHALL
apply across all sources and SHALL be managed in Settings, beside the
ComicVine ignore list — not per-source on the Sources screen. It SHALL
**ship with a curated default set** of unambiguous non-comic publisher
houses (role-playing/game and tech/textbook publishers) so a fresh install
filters common non-comic bundle content with no setup; every default entry
SHALL be operator-removable, and publishers of genuine comics are
deliberately excluded from the defaults (the recoverable-visibility rule is
the safety valve for anything over-caught). Rule changes SHALL reclassify
only rows still in the automatic classifier's hands (review state `new`
and not operator-classified, FRG-SRC-016); matched, ignored, and
operator-classified rows never move. Reclassified items follow the existing
non-comic visibility rules (retained, hidden by default, never dropped).
An existing per-source rule list SHALL migrate into the library-wide list.

- **Milestone**: M11 (per-source origin in m6-humble-source); reshaped
  to library-wide-with-defaults in publisher-filtering.
- **Source**: mylar-feature-surface RPG-contamination handling; owner
  dogfood 2026-07-29 (empty + per-source + jargon → library-wide, seeded,
  plain-language in Settings); mirrors the curated-default posture of
  FRG-META-020.
- **Notes**: The default set is a single source-of-truth constant
  (`DEFAULT_NON_COMIC_PUBLISHERS`) referenced by the config default, the
  docs, and the tests, seeding fresh installs only — a config that already
  carries a value keeps it. Genuine-comic publishers stay off the defaults
  on the same conservative rule as FRG-META-020's reprint-house list.

#### Scenario: The list ships with removable non-comic defaults

- **WHEN** a fresh install is inspected
- **THEN** the library-wide publisher rule list carries the curated
  non-comic defaults (RPG/game and tech/textbook houses), each removable,
  and a config that already carries a value is left untouched

#### Scenario: A library-wide rule reclassifies unreviewed rows across sources

- **WHEN** the operator adds a publisher to the list and the next sync runs
- **THEN** `new` items from that publisher are classified `other` across
  every source (newly synced and previously synced alike), while matched
  or ignored items are untouched

#### Scenario: Removing a default un-filters that publisher

- **WHEN** the operator removes a default publisher (one whose books they
  do collect) and the next sync runs
- **THEN** that publisher's `new` items are classified by file shape again,
  and previously reclassified-but-unreviewed rows re-evaluate on sync

#### Scenario: Existing per-source rules migrate into the library-wide list

- **WHEN** an install that previously stored per-source publisher rules is
  upgraded
- **THEN** those rules are carried into the single library-wide list, with
  no per-source rule surface remaining


### Requirement: FRG-SRC-004 — review-first entitlement workflow

The system SHALL hold each newly discovered comic entitlement in a review state
(`new`) with a server-proposed match computed against the ComicVine catalog
(FRG-SRC-010), supporting operator actions: match to an existing
series/collection, add as new, pick any ComicVine volume via search
(FRG-UI-039), ignore, restore, and classify (mark non-comic / mark
comic, FRG-SRC-016), individually and in bulk
(FRG-SRC-011). The review-state vocabulary is `new`, `matched`,
`ignored`, and `duplicate` — the last held by copies parked behind a
byte-identical canonical row (FRG-SRC-015), which count and display like
ignored rows (excluded from pending counts and default views, listed
under their filter) and return to `new` only via restore. By default
nothing SHALL download without an operator accept
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

#### Scenario: Restore covers duplicate rows

- **WHEN** the operator restores a `duplicate` row from its filter
- **THEN** the same restore contract applies — back to `new`, proposal
  recomputed, duplicate link cleared (FRG-SRC-015)

#### Scenario: Ignore cancels in-flight acquisition

- **WHEN** the operator ignores an accepted entitlement whose download has not yet durably imported (queued, fetching, verifying, or awaiting/undergoing import)
- **THEN** nothing lands in the library for it — the grab aborts at its re-read guard or the completed download is withdrawn before any file moves — and a later restore + re-accept downloads afresh

