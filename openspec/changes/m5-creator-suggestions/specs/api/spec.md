# Delta: api — m5-creator-suggestions

## ADDED Requirements

### Requirement: FRG-API-024 — Creator bibliography resource

The API SHALL expose `GET /api/v1/creators/{id}/bibliography` serving the
cached bibliography (FRG-CRTR-005): rows carrying the CV volume id, title,
publisher, start year, and issue count, **excluding volumes whose CV id
matches a library series at read time**, plus a `state` field —
`fresh` (cache within TTL), `pending` (fetch enqueued/running), or
`never` (no fetch has succeeded yet). When the cache is absent or older
than the documented TTL (default 7 days), the GET SHALL enqueue the
deduplicated fetch command and report `pending`/stale-but-served — the
request itself SHALL issue **no** ComicVine call (FRG-API-023's
no-CV-in-API discipline extends to this sub-resource). Unknown creator id
is a 404; no secret and no unsanitized string is exposed.

- **Milestone**: M5
- **Source**: FRG-CRTR-005 (the cache this reads); FRG-API-023 (shape and
  discipline it extends); FRG-SCHED-003 (command dedup).
- **Notes**: Serving stale-while-revalidating keeps the profile usable on
  a flaky third party; the WS command push invalidates the client when
  the fetch lands.

#### Scenario: Cold cache triggers a fetch and reports pending

- **WHEN** the bibliography is requested for a creator never fetched
- **THEN** the response is an empty list with `state: "pending"`, exactly
  one deduplicated fetch command is enqueued, and no ComicVine request is
  issued by the API handler

#### Scenario: Fresh cache serves without side effects

- **WHEN** the bibliography is requested within the TTL
- **THEN** the cached rows are served with `state: "fresh"`, in-library
  volumes are excluded by the live join, and no command is enqueued

#### Scenario: Stale cache serves while revalidating

- **WHEN** the bibliography is requested after the TTL has lapsed
- **THEN** the stale rows are still served (state reflects the refresh in
  flight), and one deduplicated fetch command is enqueued
