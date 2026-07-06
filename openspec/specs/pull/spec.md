# PULL — Weekly Pull / Release Calendar Specification

## Purpose

Baseline requirements for weekly pull / release calendar, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).

## Requirements

### Requirement: FRG-PULL-001 — Metadata-derived weekly release view

The system SHALL provide a weekly release view derived from library metadata — issues of watched series grouped by store-date week, navigable to at least the previous, current, and next weeks — computed from issue records without requiring any external pull-list source.

- **Milestone**: M3
- **Source**: sonarr-architecture.md §7.1 (Calendar as metadata projection); mylar-feature-surface.md §1 (weekly pull purpose).
- **Notes**: Deliberate divergence from Mylar, where the third-party feed *is* the pull list. Foragerr inverts it: local metadata is primary (Sonarr's calendar model); the external source (next requirement) enriches and cross-checks. This keeps the feature functional when the third-party service is down.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With no pull source configured, the current-week view lists exactly the library issues whose store date falls in that week, each showing derived state (missing/wanted, downloading, downloaded, unmonitored).

### Requirement: FRG-PULL-002 — External pull-source fetch

The system SHALL fetch weekly release data from a configurable external source (default: the walksoftly/League-of-Comic-Geeks-derived JSON API) covering at least the current and previous release weeks, applying timeouts and the source's documented error codes, and SHALL surface source-outage/stale-data status in health rather than failing silently.

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 (walksoftly API, error codes 619/522/666, two-week window, stale-data behavior) and capability map PULL.
- **Notes**: Single third-party dependency — treat as optional enrichment (see previous requirement). Source URL configurable because the service is unofficial and may move. Security: new outbound integration → risk-register entry (FRG-PROC-006).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A simulated source outage (HTTP 522-equivalent) leaves the previous fetch's data intact, marks the pull source degraded in health, and the weekly view still renders from local metadata.

### Requirement: FRG-PULL-003 — Idempotent per-week storage

The system SHALL store fetched pull entries keyed by (week, entry identity) with a per-week replace-on-refresh strategy such that repeated fetches of the same week are idempotent, and each entry SHALL record publisher, series name, issue number, ComicVine IDs when supplied, and release date.

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 (weekly table wipe/re-upsert, walksoftly supplies IDs).
- **Notes**: D4 — entries carry a *link* to library issues (below), never their own wanted/downloaded status. Mylar's separate `upcoming`/`futureupcoming` tables collapse into this store plus the metadata-derived view.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Fetching the same week twice yields identical row counts and content; entries carry the source-supplied ComicVine IDs.

### Requirement: FRG-PULL-004 — Matching pull entries to the library

The system SHALL match pull entries to watched series primarily by ComicVine ID (series and issue), falling back to a guarded name match — normalized series name equal or alias match, AND issue number a plausible next-in-sequence (0 ≤ delta < 3), AND release date within the pull week ±2 days — and SHALL record unmatched or ambiguous entries as unmatched rather than guessing.

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 (new_pullcheck match types a/b/c, date-window safety check, booktype guard).
- **Notes**: Keeps Mylar's hard-won guards (sequence delta, date window, book-type guard on ID matches) as explicit acceptance fixtures. Annual matching flows through typed annual issues (SER/D2), not a separate annual-ID path.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A fixture pull week containing an ID match, a valid name+sequence match, a wrong-volume name collision (rejected by date/sequence), and an unknown series produces exactly two links and two unmatched entries.

### Requirement: FRG-PULL-005 — Refresh trigger for missing pulled issues

When a pull entry matches a watched series but no corresponding local issue record exists, the system SHALL queue a metadata refresh for that series so the issue is created (and monitored per the series' monitor-new-items policy) before the release is searched.

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 (forced series refresh when pull issue missing); sonarr-architecture.md §1.1 (MonitorNewItems).
- **Notes**: This — not a pull-side status write — is how "auto-want upcoming" works in foragerr: pull detects, refresh creates, monitoring policy wants, the normal search pipeline grabs (D1, D4). Refresh commands deduplicate on the command queue.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A pull entry for a watched series' brand-new issue, absent locally, results in a queued refresh command and — post-refresh with policy "all" — a monitored issue visible in Wanted.

### Requirement: FRG-PULL-006 — Scheduled and manual pull refresh

The system SHALL refresh pull data on a configurable schedule (default 4 h, minimum clamp to protect the third-party source) and SHALL provide a manual force-refresh command that bypasses the re-poll throttle.

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 (4-hourly job, ~2 h re-poll throttle, manual pullrecreate).
- **Notes**: Runs on the SCHED command backbone. Mylar hardcodes 4 h; foragerr makes it configurable with a clamp.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** The scheduler triggers fetch+match at the configured cadence (observable in command history); a manual refresh within the throttle window still executes.

### Requirement: FRG-PULL-007 — Pull view actions

The pull/weekly view SHALL expose per-entry actions for entries linked to library issues — toggle monitored (want/skip) and trigger an immediate search — each delegating to the canonical issue-level operations.

- **Milestone**: M3
- **Source**: mylar-feature-surface.md capability map PULL (manual want/skip/search from the pull view); sonarr-architecture.md §8 (derived state).
- **Notes**: D4. Entry display state (skipped/wanted/downloading/downloaded) is a projection of issue + queue state.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Clicking "want" on a pull entry sets the linked issue's monitored flag; "search" queues an issue-search command; neither writes any pull-side status.

### Requirement: FRG-PULL-008 — New-series surfacing (no auto-add)

The system SHALL surface pull entries for new series debuts (issue #1/#0) that are not in the library as a distinct "new this week" list with a one-click add action (invoking the standard add flow), and SHALL NOT add series automatically.

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 (future_check auto-add) and capability map PULL (auto-add of new #1s).
- **Notes**: Deliberate divergence: Mylar auto-adds via fuzzy CV search — wrong-match risk and unbounded library growth for a single-user tool. Surfacing keeps the discovery value.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A fixture week with a new #1 shows it under "new series" with an add affordance; no series record exists until the user acts.

### Requirement: FRG-PULL-009 — Future/solicited releases

The system SHALL retain pull-source entries for future-dated weeks when the source provides them and include watched-series matches in the weekly view's forward navigation.

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 (futureupcoming) and capability map PULL (future-release watching).
- **Notes**: Thin requirement by design: with derived wanted, "watching" a future issue is just monitoring it once refresh creates it — no `add2futurewatchlist` machinery.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A future-week entry for a watched series appears when navigating to that week, marked not-yet-released.

