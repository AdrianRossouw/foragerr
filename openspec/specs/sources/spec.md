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

### Requirement: FRG-SRC-014 — Group-key sibling proposal sweep on operator pick

The system SHALL, when an operator resolves a source review row to a
series — whether by matching an already-in-library series or by adding a
new one — sweep the acting entitlement's same-`group_key` siblings, scoped
to the acting entitlement's `source_id`, and rewrite each sibling's
proposal to that series. The sweep SHALL write **proposals only**: a swept sibling
keeps `review_status = "new"` and is never auto-committed, its proposed
match carries `auto = false`, and rows already `matched` or `ignored` are
never touched. The sweep SHALL run on the plain match path as well as the
add/degrade path, so picking the correct series for one row propagates the
convenience to its siblings regardless of whether that series was already
in the library. The system SHALL additionally expose a **bulk
apply-to-group** action that resolves an operator-picked series across an
explicit set of review entitlements in one request: an in-library pick
matches every member; a not-yet-added pick adds the series once and leaves
the remaining members as swept proposals for a single bulk accept.

- **Milestone**: M11 (m11-review-refinements).
- **Source**: rig dogfood 2026-07-28 (145-row groups; a search-pick on one
  row leaves siblings stale); extends the change-1 sibling sweep
  (FRG-SRC-008) whose recorded follow-up was source-scoping and whose
  original join key was the sibling's own proposed `cv_volume_id` rather
  than `group_key`.
- **Notes**: `group_key` is computed in Python (the read-path
  `stripped_key(query_term(human_name))`) scoped to one `source_id` — no
  stored column is introduced (a future option if scale demands the SQL
  pushdown the `cv_volume_id` sweep uses). Proposal-only semantics reuse
  the FRG-SRC-008 guard shape exactly; the sweep is a convenience, never a
  licence to accept unreviewed (FRG-IMP-023 review-first posture stands).

#### Scenario: A match-to-existing pick sweeps same-group siblings into proposals

- **WHEN** an operator matches one review row to an in-library series and
  other `new` rows in the same `group_key` and `source_id` exist
- **THEN** those siblings are rewritten to a proposal for that series
  (`auto = false`), their `review_status` stays `new`, and no sibling is
  committed — while rows already `matched` or `ignored` are untouched

#### Scenario: An add pick sweeps by group, not only by prior proposal

- **WHEN** an operator adds a new series for one review row and same-group
  siblings exist whose own prior proposals named a different volume or no
  plausible match
- **THEN** every `new` same-`group_key` sibling in that source is
  re-proposed to the added series, not only the ones that already proposed
  its volume

#### Scenario: Bulk apply-to-group resolves the whole group in one action

- **WHEN** an operator picks a series for a group of review entitlements
  via the bulk apply-to-group action
- **THEN** an in-library pick matches every listed member, a not-yet-added
  pick adds the series once and leaves the rest as swept proposals, and no
  member is committed except the ones the operator's action explicitly
  matches

#### Scenario: The sweep never crosses sources

- **WHEN** two sources contain review rows sharing the same `group_key`
- **THEN** a pick in one source rewrites only that source's siblings; the
  other source's rows are untouched


### Requirement: FRG-SRC-015 — md5-identical entitlement dedupe

The system SHALL link entitlements of the same source that carry the
same stored md5 into a duplicate set with exactly one canonical row
(the earliest-created member), so each byte-identical file is reviewed
once and imported once. Linking SHALL occur at sync time and via a
one-time upgrade backfill, and SHALL only ever park rows that are in
review state `new` — a matched, ignored, or already-parked row is never
re-linked or re-pointed. Parked copies take review state `duplicate`
(FRG-SRC-004): excluded from pending-review counts and default views,
never eligible for grab, accept, match, or add through any path
(explicit restore is the only way back to actionable review), retained
under their own filter, and individually restorable to independent
`new` review with their proposal recomputed — permanently: a restored
copy is never re-parked. Entitlements without a stored md5 SHALL never be linked.
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
  proposal recomputed, and no later sync ever re-parks it — restoring a
  copy is an operator decision to review it independently, and operator
  decisions are never silently reversed (the row may still serve as the
  canonical of a future set)

#### Scenario: A later arrival joins an existing set

- **WHEN** a sync discovers a third byte-identical entitlement after two
  are already linked
- **THEN** the newcomer parks behind the same canonical (never behind
  another copy), and only a matched or ignored member — or a restored
  copy's independence — freezes a set against linking

#### Scenario: A diverged copy leaves its set

- **WHEN** a later sync leaves a parked copy without a stored md5 or
  with an md5 that no longer equals its canonical's
- **THEN** that row returns to independent `new` review with its link
  cleared — a row is parked only while it demonstrably duplicates its
  canonical

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
