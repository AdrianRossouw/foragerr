## MODIFIED Requirements

### Requirement: FRG-NFR-005 — indexer and DDL politeness with failure backoff

The system SHALL enforce per-provider minimum request intervals with jitter (defaults: search serialization with inter-search delay; DDL page fetches ≥ 15 s apart; bounded pagination depth), and on provider failures SHALL escalate through a persisted backoff ladder (temporary disable with automatic recovery), honoring Retry-After where present.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §2.6 (EscalationBackOff ladder — "copy verbatim"); mylar-ddl.md §1.8 and §3.7 (DDL_QUERY_DELAY, self-disable, no-jitter/no-429-handling gaps); mylar-feature-surface.md §3 (SEARCH_DELAY, provider blocks).
- **Notes**: One shared politeness/backoff mechanism consumed by IDX/SRCH/DDL — those AREAs own which requests happen; NFR owns pacing and failure escalation. Persist backoff state so restarts don't reset a ban-avoidance cool-down.

#### Scenario: Per-indexer 2 s spacing gate is enforced

- **WHEN** multiple requests to the same indexer are issued back-to-back from any fetch path
- **THEN** consecutive requests to that provider are spaced at least 2 s apart at the HTTP layer, and the spacing gate is applied per-indexer (a busy provider does not delay requests to a different one)

#### Scenario: Consecutive failures walk the persisted escalating back-off ladder

- **WHEN** a provider returns consecutive failures
- **THEN** its disable-until state escalates through the documented ladder (1 m → ... → 24 h maximum), the ladder state is persisted so a restart does not reset the cool-down, and a single subsequent success resets the provider to no back-off

#### Scenario: Retry-After and auth failures fast-forward the ladder

- **WHEN** a provider returns a Retry-After header, or an authentication failure
- **THEN** the back-off is fast-forwarded to at least the honored interval rather than starting at the bottom of the ladder

#### Scenario: A backing-off provider is skipped by fetch paths and logged

- **WHEN** a search or RSS fetch path selects providers while one provider is within its disable-until window
- **THEN** that provider is skipped (no request is issued) and the skip is logged, while the backlog search's inter-search delay never drops below its documented floor

### Requirement: FRG-NFR-010 — resilience to external-service failure

Failure or unavailability of any external service (ComicVine, indexers, SABnzbd, GetComics, mirror hosts) SHALL NOT crash the application or wedge worker pools; affected operations SHALL fail with recorded, user-visible status while unrelated features continue.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.3/§1.8 (BACKENDSTATUS flags, log-and-continue); sonarr-architecture.md §3.5 (DownloadClientUnavailable pending reason), §2.4 (per-indexer errors swallowed in RSS fan-out).
- **Notes**: Per-handler isolation (SCHED event bus) + per-provider backoff (above) + bounded requests (above) together imply this; baselined separately because it is the testable end-to-end property.

#### Scenario: A hostile/slow indexer cannot wedge the search worker pool

- **WHEN** a search command runs against a fixture indexer that misbehaves — accepts the connection then hangs, drips bytes slowly, returns junk, or 429-storms
- **THEN** the request to that indexer is bounded by connect/read timeouts and a response byte cap, the misbehaving provider is isolated by the back-off ladder, and no search worker is left wedged

#### Scenario: Other indexers in the same command still complete

- **WHEN** the same multi-indexer search command includes both the misbehaving fixture provider and one or more healthy providers
- **THEN** the healthy providers are searched and return their results, the misbehaving provider's failure is recorded as user-visible status, and the search worker completes rather than crashing the pool

#### Scenario: End-to-end misbehaving-fixture-server test

- **WHEN** an end-to-end test drives a real search against a fixture server exhibiting the hostile/slow behaviors
- **THEN** the application does not crash or exhaust the worker pool, the failure is recorded against the provider, and unrelated features continue to operate
