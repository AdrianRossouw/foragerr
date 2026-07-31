# sources — delta for review-selection-fixes

## MODIFIED Requirements

### Requirement: FRG-SRC-004 — review-first entitlement workflow

The system SHALL hold each newly discovered comic entitlement in a review state
(`new`) with a server-proposed match computed against the ComicVine catalog
(FRG-SRC-010), supporting operator actions: match to an existing
series/collection, add as new, pick any ComicVine volume via search
(FRG-UI-039), ignore, restore, and classify (mark non-comic / mark
comic, FRG-SRC-016), individually and in bulk
(FRG-SRC-011). A restore in bulk SHALL return as soon as its rows are
back in review, leaving their proposals to the enrichment pass — the
deferral FRG-META-016 already sanctions — rather than serializing a
rate-limited catalog call per row while the operator waits; a
single-row restore recomputes inline. A deferred row SHALL
be claimable by the enrichment pass promptly — the restore SHALL leave
it with no recorded attempt and SHALL prompt the pass rather than
waiting for the next scheduled sync, and the operator's recompute
control SHALL treat an un-proposed row as a target. The review-state vocabulary is `new`, `matched`,
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
- **THEN** ignored items are excluded from pending-review counts and default views but remain listed under their filter; a single restore returns the item to `new` with its proposed match recomputed inline (a bulk restore defers that recompute, below)

#### Scenario: Restore covers duplicate rows

- **WHEN** the operator restores a `duplicate` row from its filter
- **THEN** the same restore contract applies — back to `new`, duplicate
  link cleared (FRG-SRC-015), proposal recomputed inline for a single
  restore and deferred for a bulk one

#### Scenario: Ignore cancels in-flight acquisition

- **WHEN** the operator ignores an accepted entitlement whose download has not yet durably imported (queued, fetching, verifying, or awaiting/undergoing import)
- **THEN** nothing lands in the library for it — the grab aborts at its re-read guard or the completed download is withdrawn before any file moves — and a later restore + re-accept downloads afresh


#### Scenario: A bulk restore does not wait on the catalog

- **WHEN** the operator restores many parked rows at once
- **THEN** every restorable row returns to `new` in one prompt action
  with no per-row catalog call made while the operator waits, their
  proposals are computed by the enrichment pass, and rows that were not
  parked are refused per row

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
the Non-comic scope, never dropped). Marking a matched, ignored, or parked-duplicate row
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
  under the Non-comic scope like any other non-comic row, and the sync
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
