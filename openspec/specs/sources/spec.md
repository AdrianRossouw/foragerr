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

### Requirement: FRG-SRC-013 — Frugal, convergent proposal enrichment

The system SHALL order source-enrichment work by least-recent attempt
rather than row identity: every enrichment pass stamps the rows it
touches with an attempt time, the pending set is walked
never-attempted-first then oldest-attempt-first, and a row whose
computation failed or was deferred can therefore delay only its own
retry — never the first attempt of rows behind it. Rows whose
ComicVine consultation errored SHALL respect a configurable minimum
re-attempt spacing (default one day) on the scheduled path; operator
paths (restore, the per-row search) are never spaced. The system SHALL
provide an operator-triggered, resumable bulk recompute that refreshes
stored proposals predating the ComicVine-first universe (and, on
explicit request, no-plausible-match markers) in batches through the
batch lane (FRG-META-022), stopping cleanly on budget refusal and
resuming from its attempt-ordering on the next run; it touches only
rows still in review — matched and ignored rows are never recomputed.
No-plausible-match markers computed without a ComicVine key SHALL
become eligible for recomputation when a key is configured. Budget
exhaustion continues to leave affected rows un-proposed and retryable
(the FRG-SRC-010 invariant); attempt stamps change order, never
eligibility.

#### Scenario: A failing head cannot starve the tail

- **WHEN** nightly enrichment repeatedly defers or errors on the same
  early rows while later rows have never been attempted
- **THEN** the next run attempts the never-attempted rows first, and
  the previously failing rows retry only at their turn (and, for
  errored rows, only after the re-attempt spacing)

#### Scenario: Bulk recompute is resumable and budget-polite

- **WHEN** the operator triggers a recompute of pre-ComicVine-universe
  proposals on a large source and the batch lane's budget runs out
  mid-walk
- **THEN** the run stops cleanly having refreshed a prefix, no row
  loses its existing proposal to the interruption, and re-running the
  action continues from the least-recently-attempted rows until the
  backlog is done

#### Scenario: Operator decisions are never recomputed

- **WHEN** a bulk recompute walks rows that include matched and
  ignored entitlements
- **THEN** only rows still in review are recomputed; matched and
  ignored rows are untouched

#### Scenario: A new key unlocks catalog verdicts

- **WHEN** a deployment that stored library-fallback no-match markers
  configures a ComicVine key
- **THEN** those markers become eligible for recomputation so the rows
  can receive a catalog verdict instead of remaining frozen on a
  keyless one

