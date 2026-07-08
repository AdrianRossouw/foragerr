# api — delta for m3-pull-backbone

## ADDED Requirements

### Requirement: FRG-API-019 — Pull/weekly resource endpoint

The API SHALL expose `GET /api/v1/pull?week=<iso-week>` returning the
metadata-derived weekly release projection (FRG-PULL-001) for the requested
store-date week, defaulting to the current week when `week` is omitted. The
response SHALL use the standard paging envelope (FRG-API-006) and standard
resource/error conventions (FRG-API-002), each row carrying the pull entry's
descriptive fields (publisher, series name, issue number, release date, any
source-supplied ComicVine IDs), its `match_type`
(`id` / `name_seq` / `unmatched` / `new_series`), the linked library issue id when
matched, and — for a linked entry — the matched issue's **derived state**
(missing/wanted, downloading, downloaded, or unmonitored) computed from issue and
queue records (FRG-SER-004 / FRG-DL-008), or a pending-refresh indication for a
matched-but-not-yet-created issue. The endpoint SHALL NOT expose any secret
(provider keys, credentials, the raw source URL's query auth if any). Manual pull
refresh is NOT a new endpoint — it is the existing task force-run
`POST /api/v1/system/task/pull-refresh` (FRG-API-014 / FRG-SCHED-007).

- **Milestone**: M3
- **Source**: sonarr-architecture.md §7.1 (Calendar resource); mylar-feature-surface.md
  §1 (weekly pull view); FRG-PULL-001 (the projection this exposes), FRG-API-006
  (paging envelope), FRG-API-014 (task force-run reused for manual refresh).
- **Notes**: This is the **minimal read surface** m3-pull-experience (change 2)
  builds the weekly pull screen (FRG-UI-018) and its prev/current/next navigation
  on — the endpoint accepts an arbitrary `week`, so navigation is three client calls
  with no server-side navigation state. Derived state is projected from issue +
  queue records at request time (a cheap join over the pre-matched `pull_entries`
  store), never a status held on the pull entry (D4). Per-entry actions
  (want/skip/search) in change 2 delegate to the existing issue endpoints
  (FRG-API-004 / FRG-SRCH-008) rather than to this endpoint, which is read-only.

#### Scenario: Weekly resource returns the projection for a given week

- **WHEN** `GET /api/v1/pull?week=2026-W27` is requested
- **THEN** the response is a standard paging envelope whose rows are that week's
  pull entries, each carrying its descriptive fields, `match_type`, the linked
  issue id when matched, and — for linked entries — the matched issue's derived
  state, and it contains no provider key or credential value

#### Scenario: Omitted week defaults to the current week

- **WHEN** `GET /api/v1/pull` is requested with no `week` parameter
- **THEN** the response is the projection for the current store-date week, so the
  screen's default load needs no week computation client-side

#### Scenario: Read endpoint writes nothing; refresh is the task force-run

- **WHEN** the pull resource endpoint is exercised
- **THEN** it only reads (no issue status is mutated by `GET /pull`), and the only
  way to refresh pull data via the API is the existing
  `POST /api/v1/system/task/pull-refresh` task force-run — there is no separate
  pull-refresh endpoint
