## MODIFIED Requirements

### Requirement: FRG-SRCH-001 — Unified decision engine with explainable rejections

Every candidate release from any path (RSS, automatic search, interactive search) SHALL pass through one ordered set of accept/reject specifications, where each specification returns Accept or Reject with a user-visible reason string and a rejection type of Permanent or Temporary, yielding a decision of Approved, TemporarilyRejected (all rejections temporary), or Rejected.

- **Milestone**: M1
- **Source**: sonarr-arch §3.1 (DownloadDecisionMaker, RejectionType)
- **Notes**: The single most load-bearing SRCH requirement — powers auto-grab, interactive search display, and pending releases. Specs should run cheapest-first (Sonarr's priority groups) but that is an implementation hint, not a requirement.

#### Scenario: All specifications run so the full reason list is available

- **WHEN** a candidate is evaluated and fails more than one specification
- **THEN** the engine runs every specification in the ordered set (it does not short-circuit on the first rejection) and the stored decision lists every failed specification's user-visible reason string.

#### Scenario: Outcome is Approved only when no specification rejects

- **WHEN** a candidate passes every specification
- **THEN** the decision outcome is Approved with an empty rejection list.

#### Scenario: TemporarilyRejected when every rejection is Temporary

- **WHEN** a candidate is rejected only by specifications returning rejection type Temporary (e.g. minimum release age)
- **THEN** the decision outcome is TemporarilyRejected, not Rejected.

#### Scenario: Rejected when any rejection is Permanent

- **WHEN** a candidate accrues at least one Permanent rejection (alongside any number of Temporary ones)
- **THEN** the decision outcome is Rejected and each reason — Permanent and Temporary — remains listed.

### Requirement: FRG-SRCH-002 — Release title parsing

The system SHALL parse release titles via a pure, side-effect-free function into a parsed-issue structure (series title, issue number supporting decimal and suffixed forms such as `1.5`/`1.MU`/annuals, year, format, edition tags, release group), and unparseable titles SHALL become an "unable to parse" rejection, never an exception.

- **Milestone**: M1
- **Source**: sonarr-arch §2.5 (Parser → ParsedEpisodeInfo, failures as rejections)
- **Notes**: The parser itself is likely owned by the IMP/parsing area — this requirement pins the SRCH-facing contract (pure function, comic-grade issue numbers, rejection-not-crash).

#### Scenario: Candidates parse through the single shared parser

- **WHEN** the engine evaluates a candidate release title
- **THEN** it obtains the parsed-issue structure via the one change-2 release-title parser (no engine-local parsing), so parsing behaviour is identical across RSS, automatic, and interactive paths.

#### Scenario: Parse failure becomes a rejection, never an exception

- **WHEN** the parser cannot decode a title (e.g. an empty or garbage string)
- **THEN** the candidate produces a Permanent rejection carrying the parser's machine-readable reason and the engine continues; it does not raise or propagate an exception.

#### Scenario: Comic-grade issue numbers are preserved

- **WHEN** a title with a decimal or suffixed issue number such as `1.5`, `1.MU`, or an annual is parsed
- **THEN** the parsed-issue structure records the issue number in the form that lets downstream mapping match it, rather than truncating or dropping the suffix.

### Requirement: FRG-SRCH-003 — Release-to-library mapping

Parsed releases SHALL be mapped to a library series via normalized clean titles plus user-editable per-series alternate search names/aliases, then to concrete issues, with mapping failures recorded as distinct rejection reasons (unknown series, unknown issue).

- **Milestone**: M1
- **Source**: sonarr-arch §2.5 (ParsingService.Map, RemoteEpisode); mylar-fs SER (alternate search names)
- **Notes**: Aliases replace Sonarr's scene-mapping service — user-maintained, no external alias feed.

#### Scenario: Alias maps a release to the right series

- **WHEN** a parsed release title matches a series only through one of that series' user-editable alternate search names/aliases (not its primary title)
- **THEN** the release maps to that series via the shared matching key and evaluation proceeds against it.

#### Scenario: Year/volume disambiguation between same-named series

- **WHEN** two library series share a normalized title but differ by year/volume and a parsed release carries a year
- **THEN** mapping uses the year/volume to select the correct series rather than mapping ambiguously.

#### Scenario: Unknown series is a distinct rejection

- **WHEN** a parsed release maps to no tracked series
- **THEN** the candidate is rejected with a distinct "unknown series" reason that is visible in interactive search.

#### Scenario: Unknown issue is a distinct rejection

- **WHEN** a release maps to a tracked series but its issue number matches no concrete issue of that series
- **THEN** the candidate is rejected with a distinct "unknown issue" reason.

### Requirement: FRG-SRCH-004 — Core specification set

The decision engine SHALL include at minimum these specifications: format allowed by profile; genuine upgrade over the file on disk (profile order, revision, cutoff); upgrades-allowed flag; per-format size bounds; global maximum size; usenet retention; minimum release age (Temporary); must-contain / must-not-contain terms; already in download queue (unless upgrade); already grabbed-and-imported; blocklisted (Permanent); indexer in back-off (Temporary); sufficient free disk space.

- **Milestone**: M1
- **Source**: sonarr-arch §3.2 (specification inventory with comic keep/drop calls); mylar-fs SRCH (size limits, ignore-words)
- **Notes**: Mylar's `IGNORE_SEARCH_WORDS` maps onto must-not-contain. TV-shape specs (season pack, sample, anime, scene) deliberately dropped per sonarr-arch §3.2. "Format allowed by profile" and "genuine upgrade (profile order/revision/cutoff)" are evaluated against the format profile defined by FRG-QUAL-001; at M1 the seeded default (FRG-QUAL-002) supplies the ordering, so size/term scoring specs that depend on FRG-QUAL-003/004 are inert until M2.

#### Scenario: Format not allowed by profile is rejected

- **WHEN** a candidate's parsed format is not permitted by the series' format profile
- **THEN** the format-allowed specification rejects it with a user-renderable "format not allowed" reason.

#### Scenario: Not an upgrade over the file on disk

- **WHEN** the series already has a file whose profile rung and revision are at or above the candidate's, and the cutoff is already met
- **THEN** the upgrade-allowed specification rejects the candidate as not-an-upgrade with a user-renderable reason.

#### Scenario: Minimum release age is a Temporary rejection

- **WHEN** a usenet candidate is younger than the configured minimum release age
- **THEN** it is rejected by the retention/minimum-age specification with rejection type Temporary and a user-renderable reason.

#### Scenario: Queue and blocklist stubs return empty in this change

- **WHEN** the already-queued and blocklisted specifications run
- **THEN** they consult the change-5 queue/blocklist lookups, which are stubbed to return empty in this change, so they accept every candidate here while still producing their user-renderable reasons once those lookups are populated.

### Requirement: FRG-SRCH-006 — Search-match specifications

Search-path decisions SHALL verify the candidate actually maps to the series and issue that was searched for, rejecting mismatches with explicit reasons.

- **Milestone**: M1
- **Source**: sonarr-arch §3.2 (Specifications/Search — essential under q=-only searching)
- **Notes**: With comics searchable only by free-text `q=`, wrong-series hits are the *norm*; this spec is load-bearing, not defensive.

#### Scenario: Wrong series is rejected under q=-only searching

- **WHEN** a search for series X issue 5 returns a decodable release for series Y
- **THEN** the search-match specification rejects it with an explicit "wrong series" reason rather than grabbing it.

#### Scenario: Substring series-name collision is rejected

- **WHEN** a search for "Batman" returns a release whose parsed series is "Batman Beyond" (or vice versa)
- **THEN** the candidate is rejected with a specific reason because the mapped series is not the searched series, despite the substring overlap.

#### Scenario: Year-in-title collision is rejected

- **WHEN** a search returns a release whose issue number would only match if a year embedded in the title were read as the issue (a year-in-title collision)
- **THEN** the search-match specification rejects it with a specific "wrong issue" reason.

#### Scenario: Correct series and issue passes

- **WHEN** a search for series X issue 5 returns a release that maps to series X issue 5
- **THEN** the search-match specification accepts it.

### Requirement: FRG-SRCH-007 — Prioritization comparator chain

Among approved candidates for the same issue, the system SHALL select the best release using an ordered comparator chain — format-profile rung (then revision), preferred-term/release-group score, indexer priority, bucketed usenet age (fresh ≫ day ≫ week), size closeness to preferred size — where the first non-zero comparison wins.

- **Milestone**: M1
- **Source**: sonarr-arch §3.3 (DownloadDecisionComparer, comic version)
- **Notes**: Keep Sonarr's bucketing trick (log/step buckets) so trivial deltas don't dominate. Torrent peer-count comparator inserts at M2 (see TOR).

#### Scenario: Format rung dominates indexer priority

- **WHEN** a cbz from a low-priority indexer and a cbr from a high-priority indexer are both approved under a cbz-first profile
- **THEN** the cbz is ordered first because the format-rung comparator returns non-zero before the indexer-priority comparator is consulted.

#### Scenario: Later comparators break ties left by earlier ones

- **WHEN** two candidates tie on format rung, term score, and indexer priority but differ in usenet age
- **THEN** the bucketed-age comparator (fresh ≫ day ≫ week) determines the order, and if age buckets also tie, size closeness decides.

#### Scenario: Bucketing prevents trivial deltas from dominating

- **WHEN** two candidates differ in age or size by an amount that falls within the same log/step bucket
- **THEN** that comparator returns zero and the ordering falls through to the next comparator instead of being decided by the trivial delta.

#### Scenario: Total deterministic order is property-testable

- **WHEN** any set of approved candidates for one issue is sorted
- **THEN** the comparator chain yields a total, deterministic order (stable and independent of input permutation), covered by table-driven and property tests.

### Requirement: FRG-SRCH-008 — Automatic search commands

The system SHALL provide automatic search as commands — single-issue search, missing-issues search, cutoff-unmet search — triggered after series add (per add options), after failed downloads, and on demand from UI/API, each running the decision engine over automatic-search-enabled indexers and auto-grabbing the best approved release per issue.

- **Milestone**: M1
- **Source**: sonarr-arch §2.4 (ReleaseSearchService, command triggers); sonarr-arch §1.2 (post-add search)
- **Notes**: Command-queue chassis is the SYS/backbone area; SRCH depends on it.

#### Scenario: IssueSearchCommand runs on the search pool and grabs the best release

- **WHEN** an IssueSearchCommand executes on the search command pool (size 1)
- **THEN** it queries automatic-search-enabled indexers, feeds results through the decision engine, sorts approved decisions by the comparator chain, and records a grab handoff for the top approved release per issue.

#### Scenario: SeriesSearchCommand covers each wanted issue

- **WHEN** a SeriesSearchCommand executes
- **THEN** it produces, for every wanted issue of the series, either a recorded grab handoff for the best approved release or an explainable no-grab decision carrying its rejection reasons.

#### Scenario: Replaces the change-3 inert stub

- **WHEN** an automatic search command is dispatched
- **THEN** the live command implementation defined here runs in place of the change-3 inert stub.

#### Scenario: Grab handoff is inert until change 5

- **WHEN** the best approved release is selected
- **THEN** the grab handoff is recorded but performs no actual download hand-off in this change (inert until change 5).

### Requirement: FRG-SRCH-009 — Scheduled backlog search with politeness

The system SHALL periodically re-search all wanted issues on a configurable interval, prioritizing recently released/added issues first, and SHALL serialize issue searches with a configurable inter-search delay (default ≥30 s) so indexer API limits are respected.

- **Milestone**: M1
- **Source**: mylar-fs SRCH (backlog job, tiering, SEARCHLOCK + delay); sonarr-arch §2.4 (MissingEpisodeSearch)
- **Notes**: Adopt Mylar's newest-first ordering as a simple sort; deliberately drop its two-tier `SEARCH_TIER_CUTOFF` skip mechanic (an artifact of expensive scraping) — a plain interval + ordering suffices. Wanted feeds beyond monitored issues (pull list, arcs) belong to PULL/ARC areas.

#### Scenario: Backlog walks wanted issues oldest-first with politeness spacing

- **WHEN** the scheduled BacklogSearchCommand runs over a set of wanted issues
- **THEN** it serializes per-issue searches in oldest-first order, spacing consecutive searches by the configurable inter-search delay (clamped to at least the ≥30 s default).

#### Scenario: Delay is clamped to the configured minimum

- **WHEN** the inter-search delay is configured below the enforced minimum
- **THEN** the effective spacing is clamped up to the minimum so indexer API limits are respected.

#### Scenario: Indexers in back-off are skipped

- **WHEN** an indexer is currently in back-off during a backlog run
- **THEN** the run skips that indexer for the affected searches rather than querying it.

#### Scenario: Restart-safe via the persisted command queue

- **WHEN** the process restarts mid-backlog
- **THEN** the backlog resumes from the persisted command queue rather than losing progress or re-running from the start.

### Requirement: FRG-SRCH-010 — Search result de-duplication

Search results appearing on multiple indexers SHALL be de-duplicated by release guid, preferring the decision with fewest rejections and then the higher-priority indexer.

- **Milestone**: M1
- **Source**: sonarr-arch §2.4 (ReleaseSearchService.DeDupeDecisions)
- **Notes**: Complements per-indexer guid de-dupe in IDX.

#### Scenario: Cross-indexer dedup keeps the higher-priority indexer's copy

- **WHEN** the same release (by normalized title and size bucket) is returned by two indexers of differing priority
- **THEN** cross-indexer de-duplication keeps the copy from the higher-priority indexer and drops the other, so the result appears once.

#### Scenario: Per-indexer guid dedup runs first

- **WHEN** a single indexer returns the same guid more than once
- **THEN** per-indexer guid de-duplication collapses those before cross-indexer de-duplication by normalized title + size bucket is applied.

#### Scenario: Distinct releases are not collapsed

- **WHEN** two results share neither guid nor the same normalized-title-plus-size-bucket key
- **THEN** both are retained as distinct candidates.

### Requirement: FRG-SRCH-014 — Interactive search

The system SHALL provide an interactive search endpoint that runs a live search over interactive-enabled indexers and returns every decision — approved, temporarily rejected, and rejected — with its rejection reasons, caching results (~30 min, keyed indexer+guid) so a subsequent grab request references the cache and returns a clear "search again" error when expired.

- **Milestone**: M1
- **Source**: sonarr-arch §2.4 (interactive path), §7.2 (release endpoint semantics)
- **Notes**: Pulled into M1 despite not being named in the slice: it is the primary debugging/UX surface for the q=-only search problem and costs little once the decision engine records reasons (which M1 already requires).

#### Scenario: Returns every decision with full reason lists, comparator-sorted

- **WHEN** an interactive search runs over interactive-enabled indexers
- **THEN** the response includes every decision — Approved, TemporarilyRejected, and Rejected — each carrying its full rejection reason list, sorted by the comparator chain (approved best-first).

#### Scenario: Each row carries an indexerId+guid cache key

- **WHEN** the interactive search returns a row
- **THEN** the row carries its indexerId + guid cache key and the decision set is cached server-side for approximately 30 minutes.

#### Scenario: Grab from cache references the cached decision

- **WHEN** a grab request references a row's indexerId+guid while its cache entry is still valid
- **THEN** the grab uses the cached decision without re-running the search.

#### Scenario: Grab after cache expiry returns a deterministic 404-class error

- **WHEN** a grab request references an indexerId+guid whose cache entry has expired
- **THEN** the endpoint returns a deterministic 404-class "search again" error and never silently re-runs the search.
