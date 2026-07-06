# api — delta for m2-search-autosuggest

## ADDED Requirements

### Requirement: FRG-API-017 — ComicVine suggest (bounded lookup variant)

The API SHALL expose `GET /series/lookup/suggest?term=` returning a bounded set
of ComicVine volume candidates (first page only, approximately ten results) for
as-you-type suggestion, performing at most ONE upstream ComicVine page request
per call and NEVER the full pagination walk that `GET /series/lookup` performs.
The suggest response envelope SHALL carry `records` and a `complete` flag
(distinguishing a clean single-page fetch from one degraded by a mid-fetch
upstream failure) but SHALL NOT carry a `truncated` flag, because a suggest
result is definitionally partial (the full lookup remains the complete search).
The endpoint SHALL neutralise ComicVine filter metacharacters on `term` exactly
as the full lookup does, and SHALL honour the SAME upstream-error contract as
`GET /series/lookup`: a ComicVine authentication failure yields HTTP 503 with a
message identifying the ComicVine credential and an `errors` entry with
`field="comicvine_api_key"` as the machine-readable discriminator — never a
`200` with an empty list — and neither the response nor any log line contains
the API key value.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.1 (Series lookup / add flow, as-you-type
  suggestion); m2-lookup-error-surfacing (the `comicvine_api_key` field
  discriminator and 503 contract); FRG-API-003 (the full lookup this bounds),
  FRG-META-003/004 (rate limiting + bounded pagination).
- **Notes**: A cheap accelerator over FRG-API-003's full lookup, not a
  replacement — it exists to back FRG-UI-005's debounced autosuggest. Reuses the
  existing outbound ComicVine integration (`ComicVineClient`) with a new
  single-page `suggest_series` fetch; reuses the full lookup route's auth/error
  mapping code (not a parallel copy) so `isComicVineAuthError` on the client
  keeps working unchanged. `have_it` annotation over the ≤10 returned ids is
  retained for parity with the full lookup; plausibility scoring MAY be omitted
  to keep the call cheap. Security (FRG-PROC-006): a new query-string endpoint
  designed to be called frequently as the user types raises an outbound
  request-amplification consideration, bounded by client ≥3-char + debounce
  gating (FRG-UI-005), the single-page server fetch, and the existing CV rate
  limiter — recorded as a `docs/security/` delta in this change.

#### Scenario: Suggest returns a bounded first page without walking

- **WHEN** `GET /api/v1/series/lookup/suggest?term=batman` is called
- **THEN** the response is a `{records, complete}` envelope of at most ~10
  ComicVine candidates from the first page only, and the client issues at most
  one upstream ComicVine page request for the call (no multi-page walk), each
  candidate carrying at least cv_volume_id, name, start year, publisher, issue
  count, image url, and a `have_it` flag for already-owned volumes

#### Scenario: Suggest has no truncated flag; partiality is expected

- **WHEN** the suggest response is inspected
- **THEN** it carries a `complete` flag but NO `truncated` flag — a clean
  single-page fetch is `complete=true`, a fetch degraded by a mid-fetch upstream
  failure is `complete=false`, and there is no cap-was-hit signal because more
  results always live behind the full `GET /series/lookup`

#### Scenario: Suggest surfaces a ComicVine auth failure identically to lookup

- **WHEN** `GET /api/v1/series/lookup/suggest?term=` is called and ComicVine
  rejects the request as unauthorized (missing, empty, or invalid API key)
- **THEN** the endpoint returns HTTP 503 with a message identifying the ComicVine
  credential and an `errors` entry with `field="comicvine_api_key"` — not a `200`
  with an empty list — matching the full lookup contract exactly, and neither the
  response body nor any log line contains the API key value

#### Scenario: Suggest neutralises ComicVine filter metacharacters

- **WHEN** `term` contains ComicVine filter metacharacters (`,` or `:`)
- **THEN** they are neutralised before the upstream filter is built, exactly as
  the full lookup does, so the term cannot inject additional ComicVine filter
  fields
