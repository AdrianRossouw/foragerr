## MODIFIED Requirements

### Requirement: FRG-API-001 — Versioned, OpenAPI-documented REST API

The backend SHALL expose all application functionality through a versioned REST API under a single version prefix (`/api/v1`), with a machine-readable OpenAPI document served by the application that describes every endpoint, request/response schema, and error shape.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.1 (route prefix `api/v3/`), §7.2 conventions; foragerr stack is FastAPI which generates OpenAPI natively.
- **Notes**: Sonarr's API is versioned but not OpenAPI-documented — deliberate divergence, free with FastAPI. All other API requirements inherit this prefix.

#### Scenario: App factory builds the application with all routes under the version prefix

- **WHEN** the FastAPI application is constructed via the app factory and its route table is enumerated
- **THEN** every application route path (excluding the health endpoint owned by DEP) begins with `/api/v1`, and constructing a second app instance via the factory yields an independent, equivalently routed application (no import-time singleton state)

#### Scenario: OpenAPI document is served and accurate

- **WHEN** `GET /api/v1/openapi.json` is requested
- **THEN** it returns a valid OpenAPI 3.x document whose paths exactly cover the registered routes (every registered route appears; no documented path lacks a registered route), including request/response schemas and the standard error shape; no UI-consumed endpoint exists outside the version prefix

### Requirement: FRG-API-002 — Standard error and resource conventions

Every API resource SHALL carry an integer `id`, use JSON request/response bodies, follow REST verb semantics (GET read, POST create, PUT full update with id from route, DELETE remove), and return validation failures as structured 400-level responses naming the offending field.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 (`RestController<TResource>` + per-verb FluentValidation, resources carry `id`, PUT id from route).
- **Notes**: Pydantic models are the FluentValidation equivalent. This is the base convention requirement other API requirements assume.

#### Scenario: Uniform error shape for all 4xx responses including validation failures

- **WHEN** a request triggers a 4xx — a PUT with an invalid field value (Pydantic validation failure), a GET for a nonexistent id (404), and a malformed JSON body
- **THEN** every response body has the uniform shape `{"message": <string>, "errors": [...]}`, with Pydantic validation errors mapped into `errors[]` entries that name the offending field; no FastAPI default `{"detail": ...}` shape leaks through

#### Scenario: Resource CRUD round-trip follows the conventions

- **WHEN** a CRUD round-trip is performed on at least one resource (POST create, GET read, PUT full update with id taken from the route path, DELETE remove)
- **THEN** the resource carries an integer `id` assigned by the system, all bodies are JSON, the PUT ignores/rejects a conflicting body id in favor of the route id, and GET after DELETE returns 404 in the uniform error shape

#### Scenario: Paged list endpoints use the shared paging envelope

- **WHEN** a paged list endpoint built on the shared paging-envelope helper is queried with `page`, `pageSize`, and a whitelisted `sortKey`/`sortDirection`
- **THEN** the response is the envelope `{page, pageSize, sortKey, sortDirection, totalRecords, records[]}` with correct `totalRecords` and correctly sorted, sliced `records[]`

#### Scenario: Unknown sort keys are rejected, never interpolated into SQL

- **WHEN** a paged endpoint is queried with a `sortKey` not on that endpoint's whitelist (including SQL metacharacter payloads such as `title; DROP TABLE--`)
- **THEN** the response is a 400 in the uniform error shape naming the parameter — not a 500 and not a silent default — and the helper's implementation maps whitelisted keys to fixed column expressions so the client-supplied string is never interpolated into an ORDER BY clause
