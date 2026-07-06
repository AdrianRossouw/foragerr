# pull — delta for m3-pull-backbone

Elaborates the approved PULL baseline (FRG-PULL-001..006) from SHALL + coarse
acceptance to implementable requirements with scenario-level acceptance. The
screen and per-entry actions (FRG-PULL-007..009, FRG-UI-018) are elaborated
separately in m3-pull-experience (M3 change 2).

## MODIFIED Requirements

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
(default: the walksoftly / League-of-Comic-Geeks-derived JSON API), covering at
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
than failing silently or discarding good data. The source is optional enrichment:
when disabled or unconfigured, no fetch occurs and FRG-PULL-001 still functions.

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 (walksoftly API, error codes 619/522/666,
  two-week window, stale-data behavior); capability map PULL.
- **Notes**: Single unofficial third-party dependency — treated as optional
  enrichment over the local-primary view (FRG-PULL-001). Source URL configurable
  because the service is unofficial and has moved. Security (FRG-PROC-006): this is
  the change's one new outbound integration + untrusted-content ingress —
  RISK-039 (integration) mitigation realised here, and the pull-source arm of
  RISK-025 (SSRF) closed via the external egress profile. Source-supplied ComicVine
  IDs are recorded as *candidates* only; they are not trusted as match authority
  (FRG-PULL-004 still guards them). Only this one source is supported — the legacy
  PreviewsWorld scrape / flat-file paths are not reimplemented.

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
