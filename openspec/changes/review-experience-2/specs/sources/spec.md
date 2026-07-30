# sources — delta for review-experience-2

## ADDED Requirements

### Requirement: FRG-SRC-015 — md5-identical entitlement dedupe

The system SHALL link entitlements of the same source that carry the
same stored md5 into a duplicate set with exactly one canonical row
(the earliest-created member), so each byte-identical file is reviewed
once and imported once. Linking SHALL occur at sync time and via a
one-time upgrade backfill, and SHALL only ever park rows that are in
review state `new` — a matched, ignored, or already-parked row is never
re-linked or re-pointed. Parked copies take review state `duplicate`
(FRG-SRC-004): excluded from pending-review counts and default views,
never eligible for grab or accept, retained under their own filter, and
individually restorable to independent `new` review with their proposal
recomputed. Entitlements without a stored md5 SHALL never be linked.
The canonical row SHALL disclose its set (copy count and each copy's
bundle identity) on the review surface (FRG-UI-029).

- **Milestone**: B (review-experience-2).
- **Source**: rig dogfood 2026-07-29 — the same volumes bought in two
  bundles reviewed as twice the rows, and the second accept downloaded
  a byte-identical file the importer then blocked with no explanation.
- **Notes**: The store-supplied md5 already persisted per entitlement is
  the only pre-download identity signal; dedupe is same-source and
  pre-grab by design (importer arbitration is unchanged). Deciding the
  canonical never silently moves a copy — copies are already parked, and
  restore is the explicit path back.

#### Scenario: Two bundles, one file, one review row

- **WHEN** a sync discovers an entitlement whose stored md5 equals that
  of an existing `new` entitlement of the same source
- **THEN** the newcomer parks as `duplicate` pointing at the earlier
  row, pending-review counts rise by zero for it, and the canonical row
  discloses the copy and its bundle

#### Scenario: Upgrade backfills existing all-new sets

- **WHEN** an install holding same-md5 entitlement pairs that are all
  still `new` is upgraded
- **THEN** a one-time backfill parks the later rows of each set as
  `duplicate` behind the earliest, and a set with any matched or ignored
  member is left entirely untouched

#### Scenario: Duplicates never download

- **WHEN** any accept, bulk accept, auto-sync pass, or grab attempt
  reaches a `duplicate` row
- **THEN** it is refused or skipped under the same contract as other
  non-`new` rows — only an explicit restore returns the row to
  actionable review

#### Scenario: Restore reviews a copy independently

- **WHEN** the operator restores a `duplicate` row
- **THEN** it returns to `new` with its duplicate link cleared and its
  proposal recomputed, and it is not re-linked while it remains decided
  or until a later sync finds it still `new` alongside its md5 twin

## MODIFIED Requirements

### Requirement: FRG-SRC-004 — review-first entitlement workflow

The system SHALL hold each newly discovered comic entitlement in a review state
(`new`) with a server-proposed match computed against the ComicVine catalog
(FRG-SRC-010), supporting operator actions: match to an existing
series/collection, add as new, pick any ComicVine volume via search
(FRG-UI-039), ignore, and restore, individually and in bulk
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
