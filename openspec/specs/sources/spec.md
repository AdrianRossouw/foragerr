# SOURCES — Store-Source Integrations Specification

## Purpose

Baseline requirements for account-backed store sources: connecting an external
storefront the operator already owns content on, syncing the entitlements it
reports, reviewing them before anything enters the library, and downloading
accepted items through the existing import pipeline. First implemented in M6
(`m6-humble-source`) with Humble Bundle as the only connectable type; the model
is generic so further storefronts add without reshaping it. Depth here is the
implemented change's scenario-level detail (FRG-PROC-003, FRG-PROC-009).
## Requirements
### Requirement: FRG-SRC-001 — store-source model and connection lifecycle

The system SHALL model external store sources generically: each source has a type,
encrypted-at-rest settings, a connection state (`connected`, `expired`,
`disconnected`), and last-sync metadata. Disconnecting or session expiry SHALL never
remove or alter entitlements already synced or content already imported.

#### Scenario: Disconnect keeps synced data

- **WHEN** the operator disconnects a connected source that has synced and imported entitlements
- **THEN** the source moves to `disconnected`, its stored credential is deleted, and every entitlement row and imported file remains untouched

#### Scenario: Generic model, single implementation

- **WHEN** the sources API lists available source types
- **THEN** Humble Bundle is the only connectable type in this change (placeholder rail entries are display-only)

### Requirement: FRG-SRC-002 — Humble session-cookie authentication

The system SHALL authenticate to Humble Bundle exclusively with an operator-pasted
`_simpleauth_sess` session cookie, stored server-side and encrypted at rest via the
keystore (FRG-AUTH-008); the cookie SHALL be write-only in every API response and
redaction-registered (FRG-NFR-008). Connect SHALL validate the cookie with a live
order-list call before persisting it and SHALL report the result. The system SHALL
NOT store store-account passwords or automate login.

#### Scenario: Connect validates before saving

- **WHEN** the operator pastes a cookie and connects
- **THEN** foragerr performs a live authenticated order-list call; on success it persists the encrypted cookie and reports the order count; on failure nothing is persisted and the error names the cause (invalid/expired cookie vs. network)

#### Scenario: Cookie never leaves the server

- **WHEN** any sources API response or WebSocket message is inspected after a cookie is stored
- **THEN** the cookie value appears in none of them (a stored-value marker only), and log output redacts it

### Requirement: FRG-SRC-003 — entitlement sync

The system SHALL discover owned items by polling the Humble order API on a schedule
(default daily) and on operator demand ("Sync now"), diffing by store-native key
(gamekey + subproduct identity) so re-syncs are idempotent. Items SHALL be classified
comic/other; non-comic items SHALL be retained and visible on demand, never silently
dropped. A sync failure SHALL never crash the scheduler; malformed order entries are
skipped and logged, and partial results are kept.

#### Scenario: New purchase appears

- **WHEN** a sync runs after the operator buys a bundle containing comics
- **THEN** each new comic item appears exactly once as a `new` entitlement with title, format, and a proposed library match, and a subsequent sync creates no duplicates

#### Scenario: Non-comic items discoverable

- **WHEN** a synced bundle contains games and books alongside comics
- **THEN** the non-comic items exist as `other`-classified entitlements, hidden by default and listed when the operator shows them

### Requirement: FRG-SRC-004 — review-first entitlement workflow

The system SHALL hold each newly discovered comic entitlement in a review state
(`new`) with a server-proposed match, supporting operator actions: match to an
existing series/collection, add as new, ignore, and restore, individually and in
bulk. By default nothing SHALL download without an operator accept action. A
per-source auto-sync toggle MAY automate accept-and-download for confidently matched
new items and SHALL default to OFF.

#### Scenario: Default requires operator action

- **WHEN** a sync discovers new comic entitlements on a source with default settings
- **THEN** no download or library mutation occurs until the operator acts on each item (or bulk-accepts)

#### Scenario: Auto-sync is opt-in

- **WHEN** the operator enables the auto-sync toggle and a sync later finds a confidently matched new item
- **THEN** that item is accepted and downloaded automatically, and items below the confidence threshold remain in review

#### Scenario: Ignore and restore

- **WHEN** the operator ignores an entitlement and later restores it
- **THEN** ignored items are excluded from pending-review counts and default views but remain listed under their filter; restore returns the item to `new` with its proposed match recomputed

#### Scenario: Ignore cancels in-flight acquisition

- **WHEN** the operator ignores an accepted entitlement whose download has not yet durably imported (queued, fetching, verifying, or awaiting/undergoing import)
- **THEN** nothing lands in the library for it — the grab aborts at its re-read guard or the completed download is withdrawn before any file moves — and a later restore + re-accept downloads afresh

### Requirement: FRG-SRC-005 — session expiry as a modeled state

The system SHALL treat an authentication failure during sync as source state
`expired`: sync pauses with no automatic retries against the dead session, the
failure surfaces through the health system and UI (FRG-UI-029), and re-pasting a
valid cookie resumes sync. Expiry SHALL NOT remove or degrade any synced or imported
data.

#### Scenario: 401 pauses cleanly

- **WHEN** the Humble API returns an auth failure mid-sync
- **THEN** the source flips to `expired`, already-fetched results from that sync are kept, no further Humble calls occur until reconnection, and a health warning identifies the source with reconnect guidance

#### Scenario: Reconnect resumes

- **WHEN** the operator pastes a fresh cookie on an `expired` source
- **THEN** validation runs as on first connect, the source returns to `connected`, the health warning clears, and the next sync proceeds normally

### Requirement: FRG-SRC-006 — entitlement download and import handoff

The system SHALL download an accepted entitlement by fetching a fresh signed URL from
the order API at grab time, streaming over HTTPS to the existing download staging
area with bounded size and timeout (FRG-NFR-006), restricting destinations to the
Humble CDN host allowlist, verifying the response against the API-provided md5, and
handing the verified file to the existing import pipeline as a normal completed
download. Verification or download failures SHALL surface on the entitlement's
download state with the failure reason and a retry action (FRG-SRC-009); grab
failures deliberately do NOT enter the usenet failed-download loop, whose fused
blocklist-plus-automatic-indexer-re-search semantics are meaningless for
account-owned store content (there is nothing to blocklist or re-search).
Every import path SHALL mirror the import outcome onto the entitlement's download
state and run the FRG-SRC-007 owned-via-edition reconciliation: the automatic drain
and a manual import of a source download (FRG-PP-016) produce the same entitlement
transitions — a manually resolved source download never leaves the entitlement
stuck in a blocked or failed state.

#### Scenario: Happy path to library

- **WHEN** the operator accepts a matched entitlement
- **THEN** the file is fetched from a freshly obtained signed URL, md5-verified, imported by the standard pipeline, and the entitlement shows `matched` with its issues owned

#### Scenario: Checksum mismatch quarantined

- **WHEN** a downloaded file's md5 does not match the API metadata
- **THEN** the file is not imported (quarantined aside), the failure is recorded on the entitlement's download state with its reason, and retry is available (FRG-SRC-009)

#### Scenario: Egress confinement

- **WHEN** the order API returns a download URL whose host is outside the Humble CDN allowlist or scheme is not HTTPS
- **THEN** the download is refused and logged, and the entitlement shows a failure state

#### Scenario: Manual import mirrors the entitlement like the drain

- **WHEN** a blocked source download is resolved through manual import
  (FRG-PP-016) and its file imports successfully
- **THEN** the entitlement's download state transitions to imported in
  the same write transaction, owned-via-edition reconciliation
  (FRG-SRC-007) runs exactly as it would on the automatic drain path,
  and no stale blocked state remains on the entitlement or its queue row

### Requirement: FRG-SRC-007 — collected-edition reconciliation never suppresses singles

The system SHALL reconcile a matched collected edition against tracked single issues:
it computes and displays the exact issue range the edition fills, marks those issues
owned-via-edition on import, keeps any issue already owned as a single (no
replacement, no double-counting), and adds editions with no single-issue mapping
(OGN, artbook) as standalone items. Reconciliation SHALL never suppress an issue's
wanted state except by marking it owned — the FRG-SER-019 invariant extended to
sources.

#### Scenario: Edition fills remaining issues only

- **WHEN** an accepted edition collects issues #1–6 and #3 is already owned as a single
- **THEN** after import, #1–2 and #4–6 become owned-via-edition, #3's existing single file and record are unchanged, and no issue is counted twice

#### Scenario: Wanted semantics preserved

- **WHEN** reconciliation runs for any matched edition
- **THEN** the only wanted-state transition it produces is issues becoming owned; no unfilled issue's wanted/monitored state changes (proven the same three ways as FRG-SER-019: no suppression predicate in wanted_issues, series_statistics, or the pull matcher)

#### Scenario: No single-issue mapping

- **WHEN** an accepted entitlement is an original graphic novel or artbook with no tracked single issues
- **THEN** it imports as a standalone item without fabricating issue records

### Requirement: FRG-SRC-008 — Review-proposal freshness after library mutations

The system SHALL keep entitlement review proposals actionable as the
library changes underneath them. The add action on an entitlement whose
proposed (or explicitly supplied) ComicVine volume already exists in the
library SHALL degrade to matching the entitlement to that existing series
instead of failing. When an add action successfully creates a series, the
system SHALL, before the action returns, re-resolve the proposals of
sibling entitlements still in review whose proposal targeted the same
ComicVine volume, converting them to match proposals against the new
series so their next action succeeds on the first click. The
re-resolution need not share one database transaction with the series
add (which commits in its own steps), but every intermediate state SHALL
be self-healing: a sibling acted on before or without the sweep degrades
to the equivalent match rather than erroring.

#### Scenario: Add on an in-library volume degrades to match

- **WHEN** the operator triggers add on an entitlement whose proposed
  ComicVine volume is already present as a library series
- **THEN** the entitlement is matched to that series (identical outcome
  to the match action, including grab queueing rules), and no error is
  returned

#### Scenario: Siblings re-resolve after a successful add

- **WHEN** an add action creates a library series from ComicVine volume V
  while other entitlements in review carry proposals targeting V
- **THEN** those siblings' proposals become match proposals pointing at
  the new series, and each sibling's next single action matches it
  without an error

#### Scenario: Operator decisions are never overwritten

- **WHEN** the sibling re-resolution sweep runs
- **THEN** only entitlements still in the `new` review state are touched
  — matched and ignored entitlements are left exactly as the operator
  set them

### Requirement: FRG-SRC-009 — Failed source-download visibility and retry

The system SHALL provide an explicit retry action for an entitlement
whose download has failed, exposed as an API action and as an affordance
on the failed review row, which clears the recorded failure and re-queues
the grab through the standard grab path. The system SHALL surface failed
source downloads in application health: a source with one or more
entitlements in a failed download state degrades to a warning that
carries the failed count and remediation pointing at the source's review
screen — aggregated per source, never one health entry per entitlement.

#### Scenario: Retry re-queues a failed download

- **WHEN** the operator triggers retry on an entitlement whose download
  state is failed
- **THEN** the failure reason is cleared, the grab is re-queued through
  the standard grab task, and the download state reflects the new attempt

#### Scenario: Retry is only valid for failed downloads

- **WHEN** retry is triggered on an entitlement whose download state is
  not failed
- **THEN** the action is rejected with a conflict error and no state
  changes

#### Scenario: Failed downloads degrade health, aggregated per source

- **WHEN** a source has N > 0 entitlements whose download state is failed
- **THEN** the health surface reports one degraded component for that
  source carrying the failed count and a remediation hint, and the
  warning clears when no failed downloads remain

