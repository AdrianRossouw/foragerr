# Delta: api — m5-creators-backbone

## ADDED Requirements

### Requirement: FRG-API-023 — Creators resource and follow toggle

The API SHALL expose the creators backbone read surface using the standard
paging envelope and resource/error conventions (FRG-API-002/006):

- `GET /api/v1/creators` — paged creator rows, each carrying the creator id,
  display name, normalized role set, distinct-library-series count, the
  `followed` flag, and up to a bounded number of library work references
  (series id, title, cover availability) for card spines. Sortable by name
  and series count; filterable to followed-only. The response SHALL include
  the week's aggregate counts (total creators, followed count) needed by the
  grid header.
- `GET /api/v1/creators/{id}` — profile aggregates: per-series roles for
  every library series the creator credits, owned/total issue counts across
  those series, and the distinct publisher list.
- `PUT /api/v1/creators/{id}/follow` — body `{followed: bool}`; sets the
  user-owned flag, marks it user-touched (FRG-CRTR-004), and returns the
  updated resource. It SHALL trigger no side effects beyond the flag write.

All three SHALL expose no secret and no raw (unsanitized) ComicVine string.
Aggregates are computed from stored credits — the endpoints SHALL issue no
ComicVine request.

- **Milestone**: M5
- **Source**: design handoff §7/8 (grid fields, profile stats); FRG-CRTR-001..004
  (the data these expose).
- **Notes**: The "More from <name>" external bibliography deliberately has no
  endpoint here — it is m5-creator-suggestions scope with its own egress
  spec. Follow toggle is a PUT on a sub-resource to mirror the issue
  monitored toggle's shape.

#### Scenario: Grid rows carry the card fields without external calls

- **WHEN** `GET /api/v1/creators?page=1` is requested for a library with
  ingested credits
- **THEN** the response is a standard paging envelope whose rows carry name,
  roles, distinct-series count, `followed`, and bounded work refs, plus the
  total/followed aggregate counts — and no ComicVine request was issued

#### Scenario: Profile aggregates match stored credits

- **WHEN** `GET /api/v1/creators/{id}` is requested for a creator credited
  in two library series
- **THEN** the response carries both series with that creator's per-series
  roles, owned/total issue counts derived from issue/file records, and the
  distinct publisher list

#### Scenario: Follow toggle writes the flag and nothing else

- **WHEN** `PUT /api/v1/creators/{id}/follow` is called with
  `{followed: false}` on a seeded-followed creator
- **THEN** the flag flips off and is marked user-touched, the response
  reflects it, and no series/issue/search state changes anywhere
