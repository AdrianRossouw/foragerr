# PULL — Weekly Pull / Release Calendar Specification

## Purpose

Baseline requirements for weekly pull / release calendar, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).
## Requirements
### Requirement: FRG-PULL-001 — Metadata-derived weekly release view

The system SHALL compute a weekly release view **from local library metadata
alone**, requiring no external pull source: for a given store-date week it SHALL
yield the issues of watched series whose store date falls within that week, each
annotated with its **derived state** (missing/wanted, downloading, downloaded, or
unmonitored) computed from the issue record and current queue state (FRG-SER-004 /
FRG-DL-008) — never a status stored on a pull entry. The view SHALL be computable
for at least the previous, current, and next store-date weeks by parameterising
the target week, so a caller can navigate between weeks. This projection SHALL
remain fully functional when no pull source is configured or the source is
degraded.

- **Milestone**: M3
- **Source**: sonarr-architecture.md §7.1 (Calendar as metadata projection);
  mylar-feature-surface.md §1 (weekly pull purpose).
- **Notes**: Deliberate inversion of Mylar (where the third-party feed *is* the
  pull list). Local metadata is primary (Sonarr's calendar model); the external
  source (FRG-PULL-002) enriches and cross-checks. This change delivers the
  projection and the read endpoint that exposes it (FRG-API-019); the *screen* that
  renders it, and its prev/current/next navigation UI, are FRG-UI-018 in change 2.
  Derived state is a projection over issue + queue records — the pull store never
  holds wanted/downloaded status (D4).

#### Scenario: Current-week view derived from local metadata only

- **WHEN** the weekly view is computed for the current store-date week with no
  pull source configured
- **THEN** it lists exactly the library issues of watched series whose store date
  falls within that week, each annotated with its derived state (missing/wanted,
  downloading, downloaded, or unmonitored), and it lists nothing when no watched
  series has an issue dated in that week

#### Scenario: Adjacent weeks are navigable by parameter

- **WHEN** the view is computed for the previous week, then the current week, then
  the next week
- **THEN** each call returns exactly the watched-series issues whose store date
  falls in the requested week, so the previous/current/next weeks are each
  reachable by changing the target-week parameter

#### Scenario: View survives a missing or degraded pull source

- **WHEN** the pull source is unconfigured, disabled, or degraded (last fetch
  failed)
- **THEN** the weekly view still renders from local metadata with correct derived
  state, and the pull-source condition does not cause the view to error or empty

### Requirement: FRG-PULL-002 — External pull-source fetch

The system SHALL fetch weekly release data from a **configurable** external source
(default: the talkhard / League-of-Comic-Geeks-derived JSON API — successor to
the retired walksoftly host, 2026-05), covering at
least the current and previous release weeks per run. The fetch SHALL use the
shared hardened egress factory's **external** profile (FRG-SEC-001) applied to the
configured source URL — refusing loopback/private/link-local targets and applying
mandatory timeouts with auto-redirects disabled (FRG-NFR-006) — and SHALL treat
the response body as **untrusted input** (FRG-NFR-012), parsing it under a byte cap
into a typed entry model. The system SHALL handle the source's documented error
codes (619 bad-date, 522 backend-down, 666 client-update-required): a 619 skips the
affected week with a logged warning; a 522/666 or any transport failure is treated
as a source outage that **leaves the previously stored week intact** and marks the
pull source **degraded** in the health surface (FRG-NFR-011 / FRG-API-014) rather
than failing silently or discarding good data. The source SHALL be **enabled by
default** (owner decision 2026-07-11) so a fresh install's weekly view carries
external data without configuration; it remains fully optional — when disabled
(`pull_enabled=false`) or unconfigured, no fetch occurs, no third-party traffic is
issued, and FRG-PULL-001 still functions.

- **Milestone**: M3 (default flipped to enabled in pull-enabled-default,
  2026-07-11)
- **Source**: mylar-feature-surface.md §1 (walksoftly API, error codes 619/522/666,
  two-week window, stale-data behavior); capability map PULL; owner decision
  2026-07-11 (`docs/process/decisions.md`).
- **Notes**: Single unofficial third-party dependency — treated as optional
  enrichment over the local-primary view (FRG-PULL-001). Source URL configurable
  because the service is unofficial and has moved. Security (FRG-PROC-006): this is
  the change's one new outbound integration + untrusted-content ingress —
  RISK-039 (integration) mitigation realised here, and the pull-source arm of
  RISK-025 (SSRF) closed via the external egress profile. Source-supplied ComicVine
  IDs are recorded as *candidates* only; they are not trusted as match authority
  (FRG-PULL-004 still guards them). Only this one source is supported — the legacy
  PreviewsWorld scrape / flat-file paths are not reimplemented. Default-on posture
  (2026-07-11): every install now issues scheduled traffic to the unofficial source
  by default; owner-accepted on RISK-039, opt-out preserved.

#### Scenario: Source outage leaves stored data intact and marks health degraded

- **WHEN** a pull refresh runs and the source returns a 522-equivalent backend-down
  response (or the transport fails)
- **THEN** the previous fetch's stored week is left byte-for-byte intact, the pull
  source is marked degraded in the health surface with a remediation hint, no
  partial/empty week is written, and the weekly view (FRG-PULL-001) still renders
  from local metadata

#### Scenario: Source URL is fetched over the hardened external egress profile

- **WHEN** the configured `pull_source_url` resolves to a loopback, private, or
  link-local address
- **THEN** the fetch is refused per-hop by the external egress profile (FRG-SEC-001)
  rather than issued, and the refusal is surfaced as a degraded-source health
  condition — the pull source cannot be used to reach an internal host

#### Scenario: Untrusted / malformed source payload degrades, never crashes

- **WHEN** the source returns a malformed, oversized, or hostile JSON body
- **THEN** the parse is bounded (byte cap) and the run degrades to a source-outage
  outcome (stored week intact, source marked degraded) without raising, and no
  partially-parsed week is written

#### Scenario: Documented bad-date code skips only the affected week

- **WHEN** the source returns a 619 bad-date code for one of the requested weeks
- **THEN** that week is skipped with a logged warning while the other requested
  week is still fetched and stored, and the run is not treated as a full outage

#### Scenario: Enabled by default; disabling opts out completely

- **WHEN** a fresh install boots with no pull configuration, and separately when
  the operator sets `pull_enabled=false`
- **THEN** the fresh install's scheduled pull-refresh fetches from the default
  source (degrading gracefully if it is down), while the opted-out install issues
  no third-party traffic, its pull-refresh no-ops cleanly, and the weekly view
  still renders from local metadata

### Requirement: FRG-PULL-003 — Idempotent per-week storage

The system SHALL store fetched pull entries in a dedicated store keyed by
`(week, entry_identity)` with a **per-week replace-on-refresh** strategy executed
in a single transaction (FRG-DB-007), such that repeated fetches of the same week
are idempotent — identical row counts and content. Each entry SHALL record
publisher, series name, issue number, the source-supplied ComicVine series/issue
IDs when present, and release date, and SHALL carry a **nullable link** to a
library issue plus a `match_type` discriminator — and SHALL NOT carry its own
wanted/downloaded/skipped status (that state lives on the issue and queue, D4). The
entry identity SHALL be derived deterministically from the source entry so the same
logical release maps to the same stored entry across refreshes. The store rides the
existing versioned-migration and typed-schema discipline (FRG-DB-002 / FRG-DB-008).

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 (weekly table wipe/re-upsert, walksoftly
  supplies IDs).
- **Notes**: D4 — entries link to library issues, never hold status. Mylar's
  separate `upcoming` / `futureupcoming` tables collapse into this one store plus
  the metadata-derived view (FRG-PULL-001). `entry_identity` prefers the
  source-supplied CV issue id, else a normalized `(series_name, issue_number,
  publisher)` tuple. Leaves room for a future `booktype`/trade discriminator column
  (M3 ch5) without reworking storage. No DB-area *requirement* changes.

#### Scenario: Re-fetching a week is idempotent

- **WHEN** the same release week is fetched and stored twice in succession
- **THEN** the second store yields identical row counts and content to the first
  (replace-on-refresh), and entries carry the source-supplied ComicVine IDs where
  the source provided them

#### Scenario: Entries carry a link, not a status

- **WHEN** a stored pull entry is inspected
- **THEN** it records publisher, series name, issue number, release date, any
  source-supplied CV IDs, a nullable `matched_issue_id` link, and a `match_type` —
  and it has no wanted/downloaded/skipped status field of its own

#### Scenario: A failed refresh does not half-replace a week

- **WHEN** a refresh of a week fails partway (source error mid-run)
- **THEN** the prior stored week for that key is left intact (the replace-on-refresh
  transaction is not committed), so the store never holds a partially-replaced week

### Requirement: FRG-PULL-004 — Matching pull entries to the library

The system SHALL match stored pull entries to watched series **primarily by
ComicVine id** (series and issue), retaining a **book-type guard** so an id match to
a wrong book-type is rejected; failing an id match it SHALL attempt a **guarded name
match** accepted only when ALL of the following hold: the normalized series name
equals a watched series' name or a registered alias (reusing `library/matching.py`
normalization), AND the issue number is a plausible next-in-sequence
(`0 ≤ delta < 3`), AND the release date is within the pull week **±2 days**. Entries
that match neither, or that collide ambiguously, SHALL be recorded **unmatched**
(never guessed into a link); an unmatched `#1`/`#0` entry for a series not in the
library SHALL additionally be tagged as a new-series candidate for later surfacing.
Source-supplied ComicVine IDs SHALL be treated as match *candidates*, not authority
— they still pass the book-type guard. The resolved `match_type`
(`id` / `name_seq` / `unmatched` / `new_series`) and the issue link SHALL be
persisted on the entry (FRG-PULL-003) so the read endpoint is a join, not a re-match.

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 (new_pullcheck match types a/b/c,
  date-window safety check, booktype guard).
- **Notes**: Keeps Mylar's hard-won guards (sequence delta, date window, book-type
  guard on id matches) as explicit acceptance fixtures, over the existing
  `library/matching.py` identity machinery rather than a second implementation.
  Annual matching flows through typed annual issues (SER/D2), not a separate
  annual-id path. The `new_series` tag is *only* a tag; adding the series is a
  change-2 affordance (FRG-PULL-008), never automatic.

#### Scenario: Mixed fixture week produces exactly the guarded links

- **WHEN** a fixture pull week contains (a) an entry with a CV id matching a watched
  series' issue, (b) a valid name+sequence match within the date window, (c) a
  wrong-volume name collision whose date/sequence fail the guards, and (d) an
  unknown series
- **THEN** exactly two entries are linked (a and b) and exactly two are recorded
  unmatched (c and d) — the wrong-volume collision is rejected rather than guessed

#### Scenario: Book-type guard rejects a mismatched id match

- **WHEN** a source entry's CV id resolves to a library issue of a different
  book-type
- **THEN** the id match is rejected and the entry is not linked on the strength of
  the id alone

#### Scenario: Unmatched new #1 is tagged as a new-series candidate

- **WHEN** an unmatched entry is issue `#1` (or `#0`) for a series not in the library
- **THEN** it is recorded unmatched AND tagged as a new-series candidate, but no
  series record is created (surfacing/adding is FRG-PULL-008 in change 2)

### Requirement: FRG-PULL-005 — Refresh trigger for missing pulled issues

The system SHALL, when a pull entry matches a watched series (by id or guarded
name match) but no corresponding local issue record exists, enqueue the existing
**`refresh-series`** command for that series (FRG-META-008), deduplicated on the
command queue (FRG-SCHED-003), so metadata reconciliation creates the issue and the
series' monitor-new-items policy (FRG-SER-007) decides whether it becomes monitored
and wanted — before any search is attempted. The pull side SHALL NOT write any
issue status: detection is the pull backbone's only action, creation is
`refresh-series`, wanting is the monitoring policy, and grabbing is the normal search
pipeline (D1, D4).

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 (forced series refresh when pull issue
  missing); sonarr-architecture.md §1.1 (MonitorNewItems).
- **Notes**: This — not a pull-side status write — is how "auto-want upcoming" works
  in foragerr (deliberate divergence from Mylar's `AUTOWANT_UPCOMING`). Reuses the
  existing `refresh-series` command (`library/flows/_common.py`) with
  `triggered_by="pull-refresh"`; queue dedup prevents a busy pull week from
  enqueuing the same series twice. The entry's issue link is populated on a
  subsequent refresh once the issue exists.

#### Scenario: Missing matched issue queues a deduplicated refresh

- **WHEN** a pull entry matches a watched series but that issue does not yet exist
  locally
- **THEN** a `refresh-series` command for that series is enqueued (deduplicated on
  the command queue), and no wanted/status write is made to any issue by the pull
  side

#### Scenario: Post-refresh, monitor policy governs wanting

- **WHEN** the queued `refresh-series` completes and the series' monitor-new-items
  policy is "all"
- **THEN** the newly-created issue is monitored and appears in Wanted through the
  normal derived-state path — the pull backbone having written nothing to it

#### Scenario: Already-present matched issue triggers no refresh

- **WHEN** a pull entry matches a watched series whose issue already exists locally
- **THEN** no `refresh-series` is enqueued for that entry (the link is simply
  recorded), so a steady-state pull week does not churn refreshes

### Requirement: FRG-PULL-006 — Scheduled and manual pull refresh

The system SHALL run pull refresh (fetch → store → match → trigger) as a built-in
recurring task on the existing interval scheduler (FRG-SCHED-006) at a configurable
cadence (default 4 h) with the interval clamped to a documented minimum to protect
the unofficial third-party source, and SHALL provide a **manual force-refresh** via
the existing task force-run surface (FRG-API-014 / FRG-SCHED-007) that bypasses the
internal re-poll throttle. Each run SHALL be recorded in job history (FRG-SCHED-008)
and push status over the WS bus (FRG-SCHED-010) like any other command. An internal
re-poll throttle MAY suppress a *scheduled* fetch when the last successful fetch is
recent, but SHALL NOT suppress a manual force-run.

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 (4-hourly job, ~2 h re-poll throttle,
  manual pullrecreate).
- **Notes**: Runs on the SCHED command backbone — no bespoke scheduler. Mylar
  hardcodes 4 h; foragerr makes it configurable (`pull_refresh_interval_seconds`,
  default 14400) with a min clamp (proposed 3600 s). Manual force-refresh is
  `POST /api/v1/system/task/pull-refresh` — the same surface "back up now" uses;
  Mylar's `pullrecreate`/`manualpull` collapse into force-run (no separate
  endpoint).

#### Scenario: Scheduled refresh runs at the configured cadence

- **WHEN** the scheduler reaches the configured pull-refresh interval
- **THEN** a `pull-refresh` command runs fetch → store → match → trigger, and the
  run is observable in job history with its outcome

#### Scenario: Interval below the minimum is clamped

- **WHEN** `pull_refresh_interval_seconds` is configured below the documented
  minimum clamp
- **THEN** the effective interval is raised to the clamp (logged), so the
  third-party source is never polled faster than the floor allows

#### Scenario: Manual force-refresh bypasses the re-poll throttle

- **WHEN** `POST /api/v1/system/task/pull-refresh` is invoked within the internal
  re-poll throttle window
- **THEN** the refresh still executes now (timer reset, deduplicated), returning the
  enqueued command's id — the throttle suppresses only scheduled fetches, not a
  manual force-run

### Requirement: FRG-PULL-007 — Pull view actions

The pull/weekly view SHALL expose per-entry actions for entries **linked to a
library issue** (`matched_issue_id` set): toggle monitored (want/skip) and
trigger an immediate search. Each action SHALL delegate to the canonical
issue-level operation — the single-issue monitored update
(`PUT /api/v1/issues/{issue_id}`, FRG-API-004) and the `issue-search` command
(FRG-SRCH-008) via the command endpoint — and SHALL NOT write any pull-side
status (D4): the card's displayed state changes only because the issue/queue
projection changed. Entries without a linked issue (unmatched, new-series,
pending-refresh) SHALL NOT expose these actions.

- **Milestone**: M4
- **Source**: mylar-feature-surface.md capability map PULL (manual
  want/skip/search from the pull view); sonarr-architecture.md §8 (derived
  state); FRG-API-019 notes (actions delegate to issue endpoints; the pull
  endpoint stays read-only).
- **Notes**: D4. Reuses the existing frontend seams: the single-issue
  monitored mutation and the generic command dispatch + watcher used by the
  Wanted screen. Search completion invalidates the pull query so the card's
  derived state updates. Restated in m11-discovery-surface solely because
  the unlinked-entry scenario's cross-reference to the FRG-PULL-008 add
  affordance widened with that requirement; the issue-action behavior is
  unchanged.

#### Scenario: Want toggles the linked issue's monitored flag

- **WHEN** the user clicks "want" on a pull entry linked to an unmonitored
  library issue
- **THEN** the client issues `PUT /api/v1/issues/{issue_id}` with
  `monitored: true`, no pull-entry field is written, and the card's state
  re-projects to missing/wanted

#### Scenario: Search queues the canonical issue-search command

- **WHEN** the user triggers search on a linked pull entry
- **THEN** an `issue-search` command is dispatched with that issue's
  `series_id` and `issue_id` through the standard command endpoint, and its
  terminal status invalidates the pull view so derived state refreshes

#### Scenario: Unlinked entries expose no issue actions

- **WHEN** an unmatched or new-series entry (no `matchedIssueId`) renders
- **THEN** it offers no want/skip or search affordance (an unlinked entry
  whose series is not already in the library offers the FRG-PULL-008 add
  affordance instead)

### Requirement: FRG-PULL-008 — New-series surfacing (no auto-add)

The system SHALL offer a one-click add affordance — routing into the
standard Add flow — on **every** pull entry in the viewed week that
has no library-issue link (`matched_issue_id` null) and whose series
is not already present in the library, regardless of issue number.
When the entry carries a source-supplied ComicVine series id, the
affordance SHALL route with that id and the Add flow SHALL resolve it
to the exact volume as a preselected candidate (via FRG-API-026),
falling back to the name-prefilled search when the entry has no id or
the id does not resolve; the source id remains a *candidate* the user
visually confirms — never match authority (FRG-PULL-004 posture).
Entries tagged `new_series` (issue #1/#0 debuts, FRG-PULL-004) SHALL
render **inline in the day-grouped agenda** carrying a distinct "New"
visual badge, with a filter affordance to show debuts alone; the
previous separate "New this week" list is retired. Unlinked entries
whose series title is already in the library SHALL NOT offer the add
affordance. The system SHALL NOT add a series automatically: no
series record exists until the user completes the standard add flow,
and dismissing or ignoring any entry has no side effects.

- **Milestone**: M4 (widened + inlined + CV-id-first in M11,
  m11-discovery-surface, rig finding #17; owner ask 2026-07-29:
  adding from the Calendar should use the known ComicVine id instead
  of bouncing into a search that needs editing).
- **Source**: mylar-feature-surface.md §1 (future_check auto-add) and
  capability map PULL (auto-add of new #1s); rig finding #17 (76
  unmatched mid-run books unclickable; separate strip read as a
  second confusing stack); live payload verification 2026-07-29
  (41/72 entries carry a CV series id; issue ids nearly always
  absent, so series grain is the routing grain).
- **Notes**: Deliberate divergence from Mylar stands: no fuzzy
  auto-add. The affordance reuses the existing Add-screen prefill
  navigation seam. In-library suppression reuses the casefolded
  title-index seam the strip already used; its imprecision errs
  toward suppressing an affordance, never toward adding. Guard-failed
  entries for in-library series self-heal via refresh
  (FRG-PULL-005) — offering "Add" there would invite duplicates.

#### Scenario: Any unmatched entry for an unknown series offers add

- **WHEN** the viewed week's projection contains an `unmatched` entry
  (mid-run issue, not a #1/#0 debut) whose series is not in the
  library
- **THEN** its agenda card offers the add affordance, activating it
  routes into the Add screen (id-resolved when the entry carries a CV
  series id, name-prefilled otherwise), and any series created results
  only from the user completing that flow

#### Scenario: A CV-id entry lands on the exact volume, not a search

- **WHEN** the user activates the add affordance on an entry carrying
  a source-supplied ComicVine series id
- **THEN** the Add screen presents that resolved volume (title, year,
  publisher, poster) as the preselected candidate awaiting the user's
  confirmation and add options — no search-term editing required —
  and if the id fails to resolve, the screen degrades to the
  name-prefilled search with an honest notice

#### Scenario: Debuts render inline with a New badge, no separate list

- **WHEN** the viewed week's projection contains `new_series` entries
- **THEN** they appear in the day-grouped agenda in date position
  carrying a "New" badge plus the add affordance — no separate "New
  this week" list renders — and a debut filter shows them alone on
  demand

#### Scenario: In-library series never gets an add affordance

- **WHEN** an unlinked entry's series title matches a series already
  in the library (a guard-failed `unmatched` row, or a `new_series`
  row whose series was added since tagging)
- **THEN** the card offers no add affordance (the entry self-heals via
  the normal refresh/match path)

#### Scenario: No auto-add, no side effects

- **WHEN** the user views, filters, or ignores a week containing
  unmatched and new-series entries without completing any add flow
- **THEN** no series record is created and no pull-side state changes

#### Scenario: A debut-free week offers no debut filter

- **WHEN** the viewed week's projection contains no `new_series`
  entries in the current scope (none tagged, or all filtered out)
- **THEN** no "New" badge and no debut-filter affordance render — the
  surface never offers a filter that would resolve to an empty view
  (the successor to the retired "no new-series, no strip" behavior)

### Requirement: FRG-PULL-009 — Future/solicited releases

The system SHALL fetch and retain pull-source entries for the **next** ISO
week, in addition to the current and previous weeks, when the source provides
them: the pull-refresh run requests the future week and stores its entries
through the same idempotent per-week replace and matching pipeline
(FRG-PULL-003/004). A future week for which the source has no data yet (a
documented bad-date/619 response or an empty payload) SHALL be skipped with a
logged note without affecting the run's handling of the current and previous
weeks. The weekly view's forward navigation SHALL then include watched-series
matches for the future week, presented as not-yet-released; monitoring/search
behavior for such issues is unchanged (derived state, FRG-PULL-005's
refresh-trigger path applies as usual).

- **Milestone**: M4
- **Source**: mylar-feature-surface.md §1 (futureupcoming) and capability map
  PULL (future-release watching); FRG-PULL-002 ("at least the current and
  previous release weeks" — this widens the window without amending it).
- **Notes**: Thin by design: with derived wanted, "watching" a future issue
  is just monitoring it once refresh creates it — no `add2futurewatchlist`
  machinery. No storage change: `pull_entries` already keys by `(week,
  entry_identity)`; only the command's fetch window changes. The re-poll
  throttle and cadence (FRG-PULL-006) are untouched.

#### Scenario: Refresh stores next-week entries when the source provides them

- **WHEN** a pull refresh runs and the source returns data for the next ISO
  week
- **THEN** those entries are stored under that week's key via the standard
  replace-on-refresh transaction and matched like any other week, and a
  repeat refresh is idempotent for that week

#### Scenario: Future week appears in forward navigation, marked unreleased

- **WHEN** a stored future-week entry matches a watched series and the user
  navigates the Calendar to that week
- **THEN** the entry appears in that week's agenda marked not-yet-released,
  with derived state from the issue/queue projection as usual

#### Scenario: Source without future data degrades to a skipped week only

- **WHEN** a pull refresh requests the next week and receives a 619
  bad-date response (or an empty payload)
- **THEN** the future week is skipped with a logged note, the current and
  previous weeks are still fetched and stored normally, and the run is not
  recorded as an outage

### Requirement: FRG-PULL-010 — First-run backfill window

A pull refresh SHALL widen its fetch window to include the previous
`pull_backfill_weeks` ISO weeks (default 4, `0` disables, values above 12
clamped to 12) when — and only when — the pull store contains no stored
weeks. Backfilled weeks flow through the same fetch client, shipdate-derived
per-week storage, matching, and refresh-trigger pipeline as the standard
window (FRG-PULL-002/003/005); once any week is stored, subsequent refreshes
use the standard window only.

#### Scenario: Empty store backfills

- **WHEN** a pull refresh runs with `pull_backfill_weeks: 4` and no stored pull weeks exist
- **THEN** the fetch window covers the previous four ISO weeks in addition to previous/current/next, and fetched entries store and match through the normal pipeline under their shipdate-derived weeks

#### Scenario: Non-empty store never backfills

- **WHEN** a pull refresh runs and at least one pull week is already stored
- **THEN** the fetch window is the standard previous/current/next only — no historical week is requested

#### Scenario: Disable and cap

- **WHEN** `pull_backfill_weeks` is `0`, or configured above the cap
- **THEN** `0` performs no backfill even on an empty store, and an over-cap value is clamped to 12 with the effective value logged

### Requirement: FRG-PULL-011 — Pull payload enrichment ingestion

The pull ingest SHALL parse and store, per entry, the payload's
display-only enrichment fields the store previously dropped: a single
cover URL (the primary cover, else the first), description, creators
(role and name), characters (name), and UPC — as nullable columns on
the stored pull entry, riding the idempotent per-week
replace-on-refresh transaction (FRG-PULL-003) with no status field
added (D4 upheld). The cover URL SHALL be canonicalized (query and
fragment stripped) and validated **fail-closed** against the same
allowlist rule evaluation the cover proxy enforces (FRG-META-021):
a URL that is relative, non-HTTPS, off-host, off-prefix, or contains
traversal SHALL store as absent while the entry otherwise stores
normally. Text fields SHALL pass the existing untrusted-payload
sanitization (bidi/zero-width strip) and SHALL be length-bounded, and
list fields count-capped, within the existing payload byte cap
(FRG-PULL-002).

- **Milestone**: M11 (m11-discovery-surface).
- **Source**: rig cover-URL facts 2026-07-23 + live payload
  verification 2026-07-29 (covers on the shared S3 endpoint under
  `/comicgeeks/`, relative no-cover placeholder, description/creators/
  characters/upc coverage); RISK-039 (hostile source now supplies
  fetch targets — ingest is the trust boundary).
- **Notes**: Migration 0029, additive nullable columns, inert to older
  code. Source-internal creator/character ids are dropped (nothing
  links to them). Enrichment is budget-free — no ComicVine
  involvement. Existing stored weeks populate on their next refresh;
  no backfill command.

#### Scenario: Enrichment stores idempotently with a canonical cover

- **WHEN** a week whose payload carries covers (with volatile query
  cache-busters), descriptions, creators, characters, and UPCs is
  fetched and stored twice
- **THEN** both stores yield identical rows, each entry carries the
  primary cover URL query-stripped plus its sanitized text fields, and
  no status column exists on the store

#### Scenario: Hostile or placeholder cover URLs fail closed

- **WHEN** a payload entry's covers are any of: the relative no-cover
  placeholder, an `http://` URL, an off-host URL, a shared-S3 URL
  outside the required prefix, or a traversal-bearing URL
- **THEN** the entry stores with an absent cover (all other fields
  intact), no fetch is attempted at ingest, and the run completes
  normally

#### Scenario: Oversized and control-laden text is bounded, never fatal

- **WHEN** a payload entry carries a description beyond the length
  cap, creator lists beyond the count cap, or names containing
  bidi/zero-width controls
- **THEN** stored values are truncated to the caps and sanitized, and
  the week's ingest still succeeds

