# srch Spec Delta

## ADDED Requirements


### Requirement: FRG-SRCH-001 — Unified decision engine with explainable rejections

Every candidate release from any path (RSS, automatic search, interactive search) SHALL pass through one ordered set of accept/reject specifications, where each specification returns Accept or Reject with a user-visible reason string and a rejection type of Permanent or Temporary, yielding a decision of Approved, TemporarilyRejected (all rejections temporary), or Rejected.

- **Milestone**: M1
- **Source**: sonarr-arch §3.1 (DownloadDecisionMaker, RejectionType)
- **Notes**: The single most load-bearing SRCH requirement — powers auto-grab, interactive search display, and pending releases. Specs should run cheapest-first (Sonarr's priority groups) but that is an implementation hint, not a requirement.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** For a rejected release, the stored decision lists every failed specification's reason text; a release failing only the minimum-age spec is classified TemporarilyRejected, not Rejected.

### Requirement: FRG-SRCH-002 — Release title parsing

The system SHALL parse release titles via a pure, side-effect-free function into a parsed-issue structure (series title, issue number supporting decimal and suffixed forms such as `1.5`/`1.MU`/annuals, year, format, edition tags, release group), and unparseable titles SHALL become an "unable to parse" rejection, never an exception.

- **Milestone**: M1
- **Source**: sonarr-arch §2.5 (Parser → ParsedEpisodeInfo, failures as rejections)
- **Notes**: The parser itself is likely owned by the IMP/parsing area — this requirement pins the SRCH-facing contract (pure function, comic-grade issue numbers, rejection-not-crash).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A fixture corpus of real release titles (including decimal issues and annuals) parses to expected structures; a garbage title yields a rejected decision with reason.

### Requirement: FRG-SRCH-003 — Release-to-library mapping

Parsed releases SHALL be mapped to a library series via normalized clean titles plus user-editable per-series alternate search names/aliases, then to concrete issues, with mapping failures recorded as distinct rejection reasons (unknown series, unknown issue).

- **Milestone**: M1
- **Source**: sonarr-arch §2.5 (ParsingService.Map, RemoteEpisode); mylar-fs SER (alternate search names)
- **Notes**: Aliases replace Sonarr's scene-mapping service — user-maintained, no external alias feed.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A release titled with a series alias maps to the right series; a release for an untracked series is rejected with "unknown series" visible in interactive search.

### Requirement: FRG-SRCH-004 — Core specification set

The decision engine SHALL include at minimum these specifications: format allowed by profile; genuine upgrade over the file on disk (profile order, revision, cutoff); upgrades-allowed flag; per-format size bounds; global maximum size; usenet retention; minimum release age (Temporary); must-contain / must-not-contain terms; already in download queue (unless upgrade); already grabbed-and-imported; blocklisted (Permanent); indexer in back-off (Temporary); sufficient free disk space.

- **Milestone**: M1
- **Source**: sonarr-arch §3.2 (specification inventory with comic keep/drop calls); mylar-fs SRCH (size limits, ignore-words)
- **Notes**: Mylar's `IGNORE_SEARCH_WORDS` maps onto must-not-contain. TV-shape specs (season pack, sample, anime, scene) deliberately dropped per sonarr-arch §3.2. "Format allowed by profile" and "genuine upgrade (profile order/revision/cutoff)" are evaluated against the format profile defined by FRG-QUAL-001; at M1 the seeded default (FRG-QUAL-002) supplies the ordering, so size/term scoring specs that depend on FRG-QUAL-003/004 are inert until M2.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Each listed specification has at least one test producing its rejection reason; a release identical to the file on disk is rejected as not-an-upgrade.

### Requirement: FRG-SRCH-005 — RSS-mode specifications

RSS-path decisions SHALL additionally require that both the series and the specific issue are monitored, that grab history does not already satisfy the issue at cutoff, and SHALL apply the delay specification; these specifications SHALL early-accept when a search criteria (user- or system-invoked search) is present.

- **Milestone**: B
- **Source**: sonarr-arch §3.2 (RssSync specs: MonitoredEpisode, History, Delay)
- **Notes**: Milestone tied to RSS sync (below). Monitored-gating logic itself is exercised in M1 by wanted-list construction (SER area).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An unmonitored issue's release passes an interactive search decision but is rejected "not monitored" on the RSS path.

### Requirement: FRG-SRCH-006 — Search-match specifications

Search-path decisions SHALL verify the candidate actually maps to the series and issue that was searched for, rejecting mismatches with explicit reasons.

- **Milestone**: M1
- **Source**: sonarr-arch §3.2 (Specifications/Search — essential under q=-only searching)
- **Notes**: With comics searchable only by free-text `q=`, wrong-series hits are the *norm*; this spec is load-bearing, not defensive.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Searching for series X issue 5 rejects a decodable release for series Y (or issue 6) with a "wrong series/issue" reason instead of grabbing it.

### Requirement: FRG-SRCH-007 — Prioritization comparator chain

Among approved candidates for the same issue, the system SHALL select the best release using an ordered comparator chain — format-profile rung (then revision), preferred-term/release-group score, indexer priority, bucketed usenet age (fresh ≫ day ≫ week), size closeness to preferred size — where the first non-zero comparison wins.

- **Milestone**: M1
- **Source**: sonarr-arch §3.3 (DownloadDecisionComparer, comic version)
- **Notes**: Keep Sonarr's bucketing trick (log/step buckets) so trivial deltas don't dominate. Torrent peer-count comparator inserts at M2 (see TOR).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Given a cbr from a high-priority indexer and a cbz from a low-priority one under a cbz-first profile, the cbz is grabbed; comparator order is covered by table-driven tests.

### Requirement: FRG-SRCH-008 — Automatic search commands

The system SHALL provide automatic search as commands — single-issue search, missing-issues search, cutoff-unmet search — triggered after series add (per add options), after failed downloads, and on demand from UI/API, each running the decision engine over automatic-search-enabled indexers and auto-grabbing the best approved release per issue.

- **Milestone**: M1
- **Source**: sonarr-arch §2.4 (ReleaseSearchService, command triggers); sonarr-arch §1.2 (post-add search)
- **Notes**: Command-queue chassis is the SYS/backbone area; SRCH depends on it.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Adding a series with "search for missing" queues a search command whose completion results in grabs (or explainable no-grab decisions) for each wanted issue.

### Requirement: FRG-SRCH-009 — Scheduled backlog search with politeness

The system SHALL periodically re-search all wanted issues on a configurable interval, prioritizing recently released/added issues first, and SHALL serialize issue searches with a configurable inter-search delay (default ≥30 s) so indexer API limits are respected.

- **Milestone**: M1
- **Source**: mylar-fs SRCH (backlog job, tiering, SEARCHLOCK + delay); sonarr-arch §2.4 (MissingEpisodeSearch)
- **Notes**: Adopt Mylar's newest-first ordering as a simple sort; deliberately drop its two-tier `SEARCH_TIER_CUTOFF` skip mechanic (an artifact of expensive scraping) — a plain interval + ordering suffices. Wanted feeds beyond monitored issues (pull list, arcs) belong to PULL/ARC areas.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With 100 wanted issues, a scheduled run searches newest-first with observable inter-issue spacing and stops cleanly on shutdown.

### Requirement: FRG-SRCH-010 — Search result de-duplication

Search results appearing on multiple indexers SHALL be de-duplicated by release guid, preferring the decision with fewest rejections and then the higher-priority indexer.

- **Milestone**: M1
- **Source**: sonarr-arch §2.4 (ReleaseSearchService.DeDupeDecisions)
- **Notes**: Complements per-indexer guid de-dupe in IDX.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** The same NZB indexed by both DogNZB and NZB.su appears once in interactive search results, attributed to the preferred indexer.

### Requirement: FRG-SRCH-011 — RSS sync

The system SHALL run a scheduled RSS sync (configurable interval, default 15 min, minimum 10, 0 = disabled) that fetches recent releases from all RSS-enabled indexers in parallel with per-indexer errors isolated, and feeds all results plus pending releases through the decision engine to auto-grab approved wanted issues.

- **Milestone**: B
- **Source**: sonarr-arch §2.4 (RssSyncService, FetchAndParseRssService)
- **Notes**: Deliberate divergence from Mylar: NO persistent `rssdb` cache with offline SQL matching — releases are decided live per sync, Sonarr-style. The rssdb model duplicates decision logic in SQL and goes stale; explicitly excluded.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A wanted issue whose release appears in an indexer's RSS feed is grabbed within one sync interval without any live search query; one indexer erroring does not abort the sync.

### Requirement: FRG-SRCH-012 — Delay profile

The system SHALL support a delay setting that temporarily rejects RSS-sourced grabs until the release age exceeds N minutes, with bypass when the release already meets the profile cutoff, and SHALL never apply delay to user-invoked searches.

- **Milestone**: B
- **Source**: sonarr-arch §3.4 (DelayProfile, DelaySpecification)
- **Notes**: Simplified single-protocol form (one value + bypass-at-cutoff); per-protocol preference joins at M2. Valuable for comics where a poor scan often precedes the digital release by hours.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With a 120-minute delay, an early low-grade scan on RSS sits pending while a cutoff-quality release grabs immediately; an interactive grab of the pending release works at once.

### Requirement: FRG-SRCH-013 — Pending release queue

Temporarily rejected decisions and grab attempts that fail due to download-client unavailability SHALL be persisted to a pending-release store with a reason (Delay, DownloadClientUnavailable, Fallback), surfaced in the queue view as pending, re-evaluated on subsequent syncs, and Fallback releases SHALL be tried when the primary grab for the same issue fails.

- **Milestone**: B
- **Source**: sonarr-arch §3.5 (ProcessDownloadDecisions, PendingReleaseService)
- **Notes**: Three-reason model kept intact — it is how delay, client outages, and retry-fallback compose. Candidate to pull DownloadClientUnavailable handling into M1 if slice testing shows grabs being silently lost on client outage.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Killing SABnzbd during a grab leaves the release pending with reason DownloadClientUnavailable and it is grabbed automatically once the client returns.

### Requirement: FRG-SRCH-014 — Interactive search

The system SHALL provide an interactive search endpoint that runs a live search over interactive-enabled indexers and returns every decision — approved, temporarily rejected, and rejected — with its rejection reasons, caching results (~30 min, keyed indexer+guid) so a subsequent grab request references the cache and returns a clear "search again" error when expired.

- **Milestone**: M1
- **Source**: sonarr-arch §2.4 (interactive path), §7.2 (release endpoint semantics)
- **Notes**: Pulled into M1 despite not being named in the slice: it is the primary debugging/UX surface for the q=-only search problem and costs little once the decision engine records reasons (which M1 already requires).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** The UI shows a wanted issue's full candidate list with per-release rejection reasons; grabbing a listed release succeeds without re-searching; grabbing after cache expiry returns the defined error.
