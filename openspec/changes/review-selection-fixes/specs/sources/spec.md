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
single-row restore recomputes inline. The review-state vocabulary is `new`, `matched`,
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


#### Scenario: A bulk restore does not wait on the catalog

- **WHEN** the operator restores many parked rows at once
- **THEN** every restorable row returns to `new` in one prompt action
  with no per-row catalog call made while the operator waits, their
  proposals are computed by the enrichment pass, and rows that were not
  parked are refused per row
