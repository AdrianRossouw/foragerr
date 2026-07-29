# pull — delta for m11-discovery-surface

## MODIFIED Requirements

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

- **Milestone**: M4; widened + inlined + CV-id-first in M11
  (m11-discovery-surface, rig finding #17; owner ask 2026-07-29:
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

## ADDED Requirements

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
