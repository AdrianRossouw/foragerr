# api — delta for m11-discovery-surface

## ADDED Requirements

### Requirement: FRG-API-026 — ComicVine lookup by volume id

The API SHALL expose `GET /series/lookup/volume/{cv_volume_id}`
resolving a single ComicVine volume id to one lookup candidate in the
same resource shape as `GET /series/lookup` (title, year, publisher,
remote poster, external id, sanitized description, `have_it`
annotation), performing at most one upstream ComicVine volume fetch
per call on the **interactive** lane (FRG-META-022). The endpoint
SHALL honour the same upstream-error contract as the term lookup: a
ComicVine authentication failure yields HTTP 503 with the
`comicvine_api_key` field discriminator — never an empty 200 — and no
response or log line contains the API key value. An id ComicVine does
not recognize SHALL yield a structured 404-class response the client
can distinguish from a transport failure, so callers can degrade to a
term search.

- **Milestone**: M11 (m11-discovery-surface).
- **Source**: FRG-API-003 (the term lookup whose candidate shape and
  error contract this reuses); FRG-API-017 (the pattern: a lookup
  variant is its own requirement); FRG-PULL-008 (the Calendar
  CV-id-first add affordance this serves; owner ask 2026-07-29).
- **Notes**: Reuses `ComicVineClient.get_volume` and the lookup
  route's auth/error mapping (not a parallel copy). One interactive
  acquisition per user add-click — no new budget pressure class.
  Security (FRG-PROC-006): no new attack-surface class — an
  authenticated, integer-parameterized variant of an existing
  outbound integration under the existing rate limiter and lanes;
  rationale recorded here, no `docs/security/` delta beyond this
  change's cover-proxy work.

#### Scenario: A known volume id resolves to one candidate

- **WHEN** `GET /api/v1/series/lookup/volume/{id}` is called with an
  id ComicVine recognizes
- **THEN** the response carries exactly one candidate in the lookup
  resource shape with `have_it` annotated, having issued at most one
  upstream ComicVine fetch on the interactive lane

#### Scenario: An unknown id is distinguishable from an outage

- **WHEN** the endpoint is called with an id ComicVine reports as
  nonexistent, and separately when the upstream fetch fails in
  transport
- **THEN** the nonexistent id yields the structured 404-class
  response and the transport failure yields the standard upstream
  error contract — the two are machine-distinguishable

#### Scenario: Auth failure follows the lookup contract

- **WHEN** the endpoint is called while the ComicVine key is missing
  or invalid
- **THEN** the response is HTTP 503 carrying the `comicvine_api_key`
  field discriminator, and the key value appears in no response body
  or log line
