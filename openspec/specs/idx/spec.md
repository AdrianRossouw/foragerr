# IDX — Indexers Specification

## Purpose

Baseline requirements for indexers, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).

## Requirements

### Requirement: FRG-IDX-001 — Indexer configuration model

The system SHALL persist each indexer as a configuration row comprising name, implementation identifier, protocol, priority (default 25), enabled flag, and implementation-specific settings serialized as JSON validated against that implementation's settings contract.

- **Milestone**: M1
- **Source**: sonarr-arch §2.1 (ThingiProvider pattern); mylar-fs IDX (newznab tuples)
- **Notes**: One `indexers` table, not Mylar's `#`-delimited config-ini tuples. Meta-indexers (NZBHydra/Prowlarr) need no special-casing — they are plain Newznab rows; deliberately drop Mylar's `[local]`/`[nzbhydra]` host annotations.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Two Newznab indexers (DogNZB, NZB.su) with different base URLs/API keys/categories coexist as rows of one table; an invalid settings payload is rejected at save time with field-level errors.

### Requirement: FRG-IDX-002 — Per-indexer usage toggles

Each indexer SHALL carry three independent toggles — enable RSS, enable automatic search, enable interactive search — and every fetch path SHALL select only indexers whose corresponding toggle is on.

- **Milestone**: M1
- **Source**: sonarr-arch §2.1 (EnableRss/EnableAutomaticSearch/EnableInteractiveSearch)
- **Notes**: RSS toggle ships in M1 even though RSS sync itself is B (see SRCH) so schema needs no later migration.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With automatic search disabled on indexer A, a wanted-issue search queries only indexer B while interactive search may still query A if its interactive toggle is on.

### Requirement: FRG-IDX-003 — Connectivity test and dynamic settings schema

The system SHALL expose a schema endpoint describing each indexer implementation's settings fields and a test action that performs a live query against the configured indexer, and SHALL report failure reasons before the definition is saved as enabled.

- **Milestone**: M1
- **Source**: sonarr-arch §7.2 (provider schema pattern); mylar-fs IDX (provider CRUD API)
- **Notes**: This is the extensibility seam for adding future indexer/DDL implementations with zero frontend work.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `GET /indexer/schema` returns field metadata sufficient to render the settings form without frontend changes per implementation; `POST /indexer/test` against a wrong API key returns a distinguishable authentication error.

### Requirement: FRG-IDX-004 — Newznab capabilities probe

The Newznab implementation SHALL fetch and cache each indexer's `?t=caps` response (cache lifetime ~7 days) and SHALL consult it for supported search parameters, page-size limits, and the category tree offered to the user.

- **Milestone**: M1
- **Source**: sonarr-arch §2.3 (NewznabCapabilitiesProvider)
- **Notes**: Keeps the door open for id-based query forms later even though comics have none today.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Category options in the indexer settings UI are populated from the live caps response; a caps-reported page limit smaller than the default is honored in paging requests.

### Requirement: FRG-IDX-005 — Newznab query generation

The Newznab request generator SHALL be tiered, emitting for comics a cleaned-title `q=` text search (punctuation normalized, `&`→`and`, whitespace→`+`) restricted to the configured categories (default 7030 Books/Comics), with issue-number zero-padding variants, paging via `offset`/`limit`, and a hard result cap (~1000 per fetch).

- **Milestone**: M1
- **Source**: sonarr-arch §2.3 (NewznabRequestGenerator, comic note); mylar-fs SRCH (zero-padding variants)
- **Notes**: Keep Sonarr's tier structure (id tier empty for now) so smarter query forms can be added without redesign. Multi-category per indexer supported (Mylar parity).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A search for series "Saga" issue 61 emits `t=search`-family requests containing the cleaned title and category 7030, pages until exhaustion or cap, and produces distinct query variants for `61`/`061` when needed.

### Requirement: FRG-IDX-006 — Newznab response parsing and error mapping

The Newznab parser SHALL convert RSS/XML items into normalized release records (guid, title, size, download URL, publish date, category, indexer attribution) and SHALL map Newznab `<error code>` responses to typed failures distinguishing at least invalid-API-key and request-limit-reached.

- **Milestone**: M1
- **Source**: sonarr-arch §2.3 (NewznabRssParser)
- **Notes**: Request-limit failures must feed the back-off ladder's fast-forward path (below).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A response with `<error code="101">` produces an auth failure surfaced in indexer health, not an empty result set; a valid feed yields releases with all required fields populated.

### Requirement: FRG-IDX-007 — Release normalization and de-duplication

After each fetch, the system SHALL de-duplicate releases by guid and stamp every release with indexer id, indexer name, protocol, and indexer priority before it enters the decision engine.

- **Milestone**: M1
- **Source**: sonarr-arch §2.2 (IndexerBase.CleanupReleases)
- **Notes**: Cross-indexer de-dupe (same title from two indexers) is handled at decision level (see SRCH result de-dupe), not here.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** The same release returned twice by one indexer appears once; every release entering decisions carries indexer attribution.

### Requirement: FRG-IDX-008 — Per-indexer request rate limiting

The system SHALL enforce a minimum interval (default 2 s) between consecutive HTTP requests to the same indexer, including across paging.

- **Milestone**: M1
- **Source**: sonarr-arch §2.2 (per-indexer rate limiting)
- **Notes**: Distinct from the DDL provider's 15 s site-scrape politeness (see DDL) and from SRCH's inter-issue search delay.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A multi-page search against one indexer shows request timestamps ≥2 s apart; concurrent searches against different indexers are not serialized against each other.

### Requirement: FRG-IDX-009 — Usenet retention parameter

The system SHALL support a global usenet retention setting (days) that is passed as `maxage` on Newznab queries and enforced as a decision-engine rejection for releases older than retention.

- **Milestone**: M1
- **Source**: sonarr-arch §3.2 (RetentionSpecification); mylar-fs IDX (USENET_RETENTION maxage)
- **Notes**: Both halves (query param + spec) required — the query param alone is advisory since indexers may ignore it.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With retention 3000 days, a 4000-day-old release is rejected with a visible "older than retention" reason.

### Requirement: FRG-IDX-010 — Indexer failure back-off and recovery

On indexer request failure, the system SHALL escalate the indexer through a back-off ladder (approx. 0 s, 1 m, 5 m, 15 m, 30 m, 1 h, 3 h, 6 h, 12 h, 24 h) setting a disabled-until time, SHALL de-escalate one level on success, SHALL fast-forward the ladder on rate-limit responses (Retry-After / request-limit errors), and SHALL exclude disabled indexers from RSS and search while showing them in health.

- **Milestone**: M1
- **Source**: sonarr-arch §2.6 (EscalationBackOff, FilterBlockedIndexers); mylar-fs SRCH (temporary provider blocks)
- **Notes**: Same mechanism is reused by download clients and the DDL provider — spec it once, generic over "provider".

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Three consecutive failures leave the indexer skipped by the next search and visible as unhealthy; one success after recovery reduces the back-off level.

### Requirement: FRG-IDX-011 — RSS gap detection

RSS fetches SHALL record a last-seen-release bookmark per indexer and page backwards on the next fetch until the bookmark is overlapped or a page cap is hit, so releases published between polls are not missed.

- **Milestone**: B
- **Source**: sonarr-arch §2.2 (RSS-gap detection via IndexerStatusService bookmark)
- **Notes**: Lands with RSS sync (SRCH, milestone B); listed here because the mechanism is per-indexer state.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With a poll gap longer than one RSS page's coverage, releases from the gap still enter decision processing.

### Requirement: FRG-IDX-012 — Torznab indexer support

The system SHALL support Torznab indexers as a Newznab-protocol implementation over the torrent protocol, reusing the caps probe, request generator, parser, and back-off machinery, with torrent-specific attributes (seeders, leechers, info-hash) captured from `torznab:attr`.

- **Milestone**: M2
- **Source**: sonarr-arch §2.3 (Torznab = same protocol over torrents); mylar-fs IDX (torznab tuples)
- **Notes**: This is the only torrent *search* surface in baseline — see TOR exclusions for tracker scrapers.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A Prowlarr/Jackett Torznab endpoint configured as an indexer returns releases marked protocol=torrent with seeder counts populated.

