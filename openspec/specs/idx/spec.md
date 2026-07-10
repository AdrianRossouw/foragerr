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

#### Scenario: Two Newznab rows coexist in one table

- **WHEN** DogNZB and NZB.su are configured as separate indexers with distinct base URLs, API keys, and category selections
- **THEN** both persist as rows of the single `indexers` table, each with implementation `newznab`, its own priority and enabled flag, and its settings serialized as JSON

#### Scenario: Invalid settings payload rejected at save with field errors

- **WHEN** an indexer is saved with a settings payload that violates the implementation's Pydantic settings contract (e.g. missing base URL or malformed field)
- **THEN** the save is rejected with field-level validation errors and no partial row is persisted

#### Scenario: API keys are held as redacted secret fields

- **WHEN** an indexer row carrying an API key is loaded
- **THEN** the API key is a `SecretStr` settings field registered for log redaction, so it is never emitted verbatim into logs or error output

### Requirement: FRG-IDX-002 — Per-indexer usage toggles

Each indexer SHALL carry three independent toggles — enable RSS, enable automatic search, enable interactive search — and every fetch path SHALL select only indexers whose corresponding toggle is on.

- **Milestone**: M1
- **Source**: sonarr-arch §2.1 (EnableRss/EnableAutomaticSearch/EnableInteractiveSearch)
- **Notes**: RSS toggle ships in M1 even though RSS sync itself is B (see SRCH) so schema needs no later migration.

#### Scenario: Automatic search honors the automatic toggle

- **WHEN** a wanted-issue automatic search runs while indexer A has enable_auto off and indexer B has it on
- **THEN** only indexer B is queried by the automatic-search fetch path

#### Scenario: Interactive path is gated independently of automatic

- **WHEN** indexer A has enable_auto off but enable_interactive on and an interactive search runs
- **THEN** indexer A is still queried by the interactive fetch path, confirming the three toggles gate their fetch paths independently

#### Scenario: RSS toggle persists in M1 schema without gating an M1 path

- **WHEN** an indexer's enable_rss toggle is set at save time
- **THEN** the value persists on the row without requiring a later migration, even though RSS sync itself lands in milestone B

### Requirement: FRG-IDX-003 — Connectivity test and dynamic settings schema

The system SHALL expose a schema endpoint describing each indexer implementation's settings fields and a test action that performs a live query against the configured indexer, and SHALL report failure reasons before the definition is saved as enabled.

- **Milestone**: M1
- **Source**: sonarr-arch §7.2 (provider schema pattern); mylar-fs IDX (provider CRUD API)
- **Notes**: This is the extensibility seam for adding future indexer/DDL implementations with zero frontend work.

#### Scenario: Schema endpoint returns renderable field metadata

- **WHEN** `GET /api/v1/indexer/schema` is called
- **THEN** it returns per-field metadata (name, type, label, help, required, secret) derived from the implementation's settings contract, sufficient to render the settings form with no per-implementation frontend changes

#### Scenario: Test action runs a live caps probe

- **WHEN** `POST /api/v1/indexer/test` is invoked against a reachable indexer with valid settings
- **THEN** it performs a live `?t=caps` probe and reports success before the definition is saved as enabled

#### Scenario: Test failure maps to a field-precise message

- **WHEN** `POST /api/v1/indexer/test` is invoked with a wrong API key
- **THEN** it returns a distinguishable authentication failure mapped to the offending field, not a generic error or a silent empty result

### Requirement: FRG-IDX-004 — Newznab capabilities probe

The Newznab implementation SHALL fetch and cache each indexer's `?t=caps` response (cache lifetime ~7 days) and SHALL consult it for supported search parameters, page-size limits, and the category tree offered to the user.

- **Milestone**: M1
- **Source**: sonarr-arch §2.3 (NewznabCapabilitiesProvider)
- **Notes**: Keeps the door open for id-based query forms later even though comics have none today.

#### Scenario: Caps drives category selection with 7030 fallback

- **WHEN** an indexer's caps response is fetched on save/test
- **THEN** the category options offered in settings are populated from the live caps response, defaulting to 7030 (Books/Comics) with a conservative fallback when caps omits it

#### Scenario: Caps response is cached per indexer with a TTL

- **WHEN** a second operation needs capabilities within the cache lifetime
- **THEN** the cached caps for that indexer are reused rather than re-fetched, and search-mode support flags are read from the cached response

#### Scenario: Probe failure degrades to recorded conservative defaults

- **WHEN** the caps probe fails for an indexer
- **THEN** the indexer degrades to conservative default parameters and that degraded state is recorded on the row rather than blocking configuration

### Requirement: FRG-IDX-005 — Newznab query generation

The Newznab request generator SHALL be tiered, emitting for comics a cleaned-title `q=` text search (punctuation normalized, `&`→`and`, whitespace→`+`) restricted to the configured categories (default 7030 Books/Comics), with issue-number zero-padding variants, paging via `offset`/`limit`, and a hard result cap (~1000 per fetch).

- **Milestone**: M1
- **Source**: sonarr-arch §2.3 (NewznabRequestGenerator, comic note); mylar-fs SRCH (zero-padding variants)
- **Notes**: Keep Sonarr's tier structure (id tier empty for now) so smarter query forms can be added without redesign. Multi-category per indexer supported (Mylar parity).

#### Scenario: Cleaned title emitted in category-restricted q= search

- **WHEN** a search runs for series "Saga" issue 61
- **THEN** the generator emits `t=search`-family requests whose `q=` carries the cleaned title via the shared sanitizing query builder (never raw CV text) and restricts results to the configured categories including 7030

#### Scenario: Tiered issue variants descend in specificity

- **WHEN** the query ladder is generated for issue 61
- **THEN** it produces descending-specificity tiers including padded issue variants (`007`/`07`/`7` forms), volume-tagged, and year-tagged queries, with tier metadata attached to each tier's results

#### Scenario: Paging honors per-tier cap and hard result cap

- **WHEN** a tier returns more results than allowed
- **THEN** the generator pages via `offset`/`limit` until exhaustion, the per-tier result cap, or the ~1000-per-fetch hard cap is reached

### Requirement: FRG-IDX-006 — Newznab response parsing and error mapping

The Newznab parser SHALL convert RSS/XML items into normalized release records (guid, title, size, download URL, publish date, category, indexer attribution) and SHALL map Newznab `<error code>` responses to typed failures distinguishing at least invalid-API-key and request-limit-reached.

- **Milestone**: M1
- **Source**: sonarr-arch §2.3 (NewznabRssParser)
- **Notes**: Request-limit failures must feed the back-off ladder's fast-forward path (below).

#### Scenario: XML parsed only via defusedxml under the byte cap

- **WHEN** a Newznab feed is parsed
- **THEN** parsing uses defusedxml exclusively (DTD/external entities/expansion disabled) under the HTTP factory's inherited byte cap, so a hostile corpus (billion-laughs, external-entity, quadratic-blowup, oversized) cannot expand or exhaust resources

#### Scenario: Error codes map to typed failures feeding back-off

- **WHEN** a response returns `<error code="101">`
- **THEN** the parser produces a typed authentication failure surfaced in indexer health (not an empty result set), and request-limit errors map to a typed limit failure that feeds the back-off ladder's fast-forward path

#### Scenario: Malformed items skipped with counts, batch survives

- **WHEN** individual items in an otherwise valid feed are malformed
- **THEN** those items are skipped and counted while the batch completes without crashing, and a valid feed yields releases with all required fields populated

### Requirement: FRG-IDX-007 — Release normalization and de-duplication

After each fetch, the system SHALL de-duplicate releases by guid and stamp every release with indexer id, indexer name, protocol, and indexer priority before it enters the decision engine.

- **Milestone**: M1
- **Source**: sonarr-arch §2.2 (IndexerBase.CleanupReleases)
- **Notes**: Cross-indexer de-dupe (same title from two indexers) is handled at decision level (see SRCH result de-dupe), not here.

#### Scenario: Duplicate guid from one indexer collapses to one candidate

- **WHEN** a single indexer returns the same guid twice in a fetch
- **THEN** per-indexer guid de-duplication at parse time yields exactly one `ReleaseCandidate` for that guid

#### Scenario: Every candidate carries indexer attribution

- **WHEN** normalized releases enter the decision engine
- **THEN** each `ReleaseCandidate` is stamped with indexer id, indexer name, protocol, and indexer priority (alongside guid, title, link, size, pubdate, tier, categories, attributes)

#### Scenario: Cross-indexer duplicates are not collapsed here

- **WHEN** two different indexers each return a release for the same content
- **THEN** both candidates pass through normalization intact, deferring cross-indexer de-duplication to the decision level (SRCH)

### Requirement: FRG-IDX-008 — Per-indexer request rate limiting

The system SHALL enforce a minimum interval (default 2 s) between consecutive HTTP requests to the same indexer, including across paging.

- **Milestone**: M1
- **Source**: sonarr-arch §2.2 (per-indexer rate limiting)
- **Notes**: Distinct from the DDL provider's 15 s site-scrape politeness (see DDL) and from SRCH's inter-issue search delay.

#### Scenario: Consecutive requests to one indexer are spaced ≥2 s

- **WHEN** a multi-page search issues consecutive requests to the same indexer
- **THEN** an asyncio gate on that indexer row spaces the request timestamps at least 2 s apart, including across paging

#### Scenario: Different indexers are not serialized against each other

- **WHEN** searches run concurrently against two different indexers
- **THEN** each indexer's request gate is independent, so requests to one are not delayed by the spacing of the other

### Requirement: FRG-IDX-009 — Usenet retention parameter

The system SHALL support a global usenet retention setting (days) that is passed as `maxage` on Newznab queries and enforced as a decision-engine rejection for releases older than retention.

- **Milestone**: M1
- **Source**: sonarr-arch §3.2 (RetentionSpecification); mylar-fs IDX (USENET_RETENTION maxage)
- **Notes**: Both halves (query param + spec) required — the query param alone is advisory since indexers may ignore it.

#### Scenario: Retention sent as maxage on the query

- **WHEN** a global usenet retention is configured and a Newznab search runs
- **THEN** the retention value is passed as `maxage=` on the outgoing query

#### Scenario: Over-retention release rejected with a visible reason

- **WHEN** retention is 3000 days and a 4000-day-old release is returned despite the advisory `maxage`
- **THEN** the decision engine rejects the release with a visible "older than retention" reason surfaced among the decision reasons

### Requirement: FRG-IDX-010 — Indexer failure back-off and recovery

On indexer request failure, the system SHALL escalate the indexer through a back-off ladder (approx. 0 s, 1 m, 5 m, 15 m, 30 m, 1 h, 3 h, 6 h, 12 h, 24 h) setting a disabled-until time, SHALL fully reset the ladder on success, SHALL fast-forward the ladder on rate-limit responses (Retry-After / request-limit errors), and SHALL exclude disabled indexers from RSS and search while showing them in health.

- **Milestone**: M1
- **Source**: sonarr-arch §2.6 (EscalationBackOff, FilterBlockedIndexers); mylar-fs SRCH (temporary provider blocks)
- **Notes**: Same mechanism is reused by download clients and the DDL provider — spec it once, generic over "provider".

#### Scenario: Repeated failures escalate the ladder and skip the provider

- **WHEN** an indexer fails several consecutive requests
- **THEN** its persisted back-off state (keyed by `(provider_type, provider_id)`) escalates through the ladder (1m→5m→15m→30m→1h→3h→6h→12h→24h), setting a next-allowed time so the next fetch skips and logs it while it stays visible as unhealthy in health

#### Scenario: Rate-limit responses fast-forward the ladder

- **WHEN** a response carries a Retry-After header or a request-limit/auth failure
- **THEN** the back-off state fast-forwards rather than stepping one level, honoring the indicated wait

#### Scenario: Success resets the back-off state

- **WHEN** a request succeeds after the provider has been backing off
- **THEN** the persisted back-off state is reset so the provider is eligible on the next fetch

#### Scenario: Ladder is generic over provider type

- **WHEN** a non-indexer provider (download client or DDL) needs the same back-off
- **THEN** it reuses the generic per-provider back-off keyed by `(provider_type, provider_id)` without any schema change

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

- **Milestone**: M7
- **Source**: sonarr-arch §2.3 (Torznab = same protocol over torrents); mylar-fs IDX (torznab tuples)
- **Notes**: This is the only torrent *search* surface in baseline — see TOR exclusions for tracker scrapers.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A Prowlarr/Jackett Torznab endpoint configured as an indexer returns releases marked protocol=torrent with seeder counts populated.

