## MODIFIED Requirements

### Requirement: FRG-API-008 — Release endpoint: interactive search with cached grab

The API SHALL provide `GET /release?issueId=` performing a live interactive search that returns every decision — approved, temporarily rejected, and rejected — each with human-readable rejection reasons, quality/format, score, indexer, size, and age; results SHALL be cached server-side (~30 min, keyed indexerId+guid) so that `POST /release {guid, indexerId}` grabs from cache and returns a clear "search again" error when the cache entry has expired.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 release endpoint semantics ("Copy this exactly"), §2.4 interactive search returning rejected decisions.
- **Notes**: This is the vertical slice's "search → grab" contract. Rejection reasons come from the decision engine (SRCH/decision area) — this owns transport only.

#### Scenario: Live search returns every decision including rejections, sorted by the comparator

- **WHEN** a client calls `GET /api/v1/release?issueId=<id>`
- **THEN** a live multi-indexer search runs and the response includes every decision — approved, temporarily rejected, and rejected — each carrying user-visible rejection reasons, quality/format, score, indexer, size, and age, and the rows are ordered by the decision comparator

#### Scenario: Response rows carry the indexerId+guid cache key and are cached ~30 min

- **WHEN** a search response is returned
- **THEN** each row carries its `indexerId` + `guid` cache key, and the results are held in a server-side cache for approximately 30 minutes with housekeeping that prunes expired entries

#### Scenario: POST on a cache hit enqueues the grab command and returns it

- **WHEN** a client calls `POST /api/v1/release {indexerId, guid}` while a matching cache entry is live
- **THEN** the endpoint enqueues the grab command (inert until change 5) and returns that command resource, without re-running a search

#### Scenario: POST on a cache miss or expiry returns a uniform 404-class error, never a silent re-search

- **WHEN** a client calls `POST /api/v1/release {indexerId, guid}` for a key that is absent or whose cache entry has expired
- **THEN** the endpoint returns a deterministic 404-class response in the uniform error shape and does not silently re-run the search

### Requirement: FRG-API-009 — Provider schema and test endpoints

For each provider family (indexers, download clients, notification connections), the API SHALL expose `GET /<provider>/schema` returning implementation templates with typed `fields[]` (name, label, type, options, advanced flag) generated from the provider's settings model, plus `POST /<provider>/test` (and `/testall`) executing a live connectivity/credentials test and returning structured pass/fail with messages.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 provider schema pattern ("the UI settings forms are 100% driven by this"), §2.1 ThingiProvider; mylar-feature-surface.md §IDX provider CRUD.
- **Notes**: M1 needs indexer + download client schemas (slice requires a working Newznab indexer and SABnzbd); notification schema ships when NOTIF ships (M2) with zero new frontend code — that is the point of the pattern.

#### Scenario: Schema endpoint returns field metadata sufficient to render the form with zero per-implementation frontend code

- **WHEN** a client calls `GET /api/v1/indexer/schema`
- **THEN** the response lists each indexer implementation with typed `fields[]` metadata (name, type, label, help, required flag, secret flag) sufficient for the settings form to be rendered generically, with no per-implementation frontend code

#### Scenario: Secret fields are write-only and never echoed in GET responses

- **WHEN** a schema or configured-provider resource containing a secret field (e.g. an API key) is returned from a GET
- **THEN** the secret field value is never echoed back — it is presented as write-only — while its `secret` flag is still surfaced in the field metadata

#### Scenario: Test endpoint runs a live caps probe and returns success or a field-precise failure

- **WHEN** a client calls `POST /api/v1/indexer/test` with a configuration
- **THEN** the endpoint executes the live capabilities probe and returns either success or a field-precise failure rendered in the uniform error shape, without persisting the configuration on failure
