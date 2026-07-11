# m5-creator-suggestions

## Why

M5's final chapter. The creator profile ships without its designed "More
from <name>" section (handoff §8): a followed creator's broader ComicVine
bibliography — the works you *don't* have — with add-to-library
affordances. That is the discovery payoff follows exist for (subscribe →
suggestions, never auto-add; 2026-07-05 domain direction).

**Live-probed integration facts (2026-07-11, per the cv-list-endpoint
lesson — probe before fixtures):** `person/4040-{id}/` with
`field_list=id,name,volume_credits` serves the person's volume stubs
(id + name only; 231 for Bill Willingham); full card data hydrates via
`volumes/?filter=id:a|b|c` (pipe-separated batch, publisher/year/count
confirmed). Issue credits already store the CV person id, so no person
lookup is needed.

## What Changes

- **Bibliography fetch + cache (FRG-CRTR-005, migration 0018)**: a
  `creator-bibliography-fetch` command (dedup, rate-gated, house command
  backbone) fetches the person's volume stubs, hydrates a bounded slice
  of NOT-in-library volumes (cap 24, newest `start_year` first), and
  replaces the creator's rows in a new `creator_bibliography` cache table;
  `bibliography_fetched_at` on the creator gates a TTL (7 days). Strings
  pass the shared CV sanitizer. Failures degrade (stale cache intact).
- **Bibliography read (FRG-API-024)**: `GET
  /api/v1/creators/{id}/bibliography` serves the cache with a `state`
  (`fresh` / `pending` / `never`), enqueuing the fetch command
  (deduplicated) when absent or stale — the GET itself issues no
  ComicVine request, preserving FRG-API-023's no-CV-in-API discipline.
  In-library volumes are excluded at read time by joining on
  `series.cv_volume_id`.
- **Profile "More from" section (FRG-UI-028 amended)**: per handoff §8 —
  work cards (title, publisher/year meta, role where known) each with an
  **Add to library** button opening the standard add flow prefilled
  (cvVolumeId-aware where the add screen supports it, else the series
  name); a pending state while the first fetch runs; the section is
  absent for creators with an empty fetched bibliography. The system
  never adds automatically.
- **Security (FRG-PROC-006)**: new untrusted-content parser (person
  detail + volume stubs) on the existing hardened client — RISK-011 note;
  no new egress profile, no SOUP change.

## Capabilities

### New Capabilities

_None (CRTR/API areas exist)._

### Modified Capabilities

- `crtr`: new FRG-CRTR-005 (bibliography fetch/cache).
- `api`: new FRG-API-024 (bibliography resource + trigger semantics).
- `ui`: FRG-UI-028 amended ("More from" section).

## Non-goals

- **No auto-add, ever** (standing rule); the Add button routes into the
  user-driven add flow.
- No bibliography for unfollowed creators beyond on-demand profile views
  (the fetch triggers from the profile regardless of follow state — the
  cap and TTL bound the cost; follows may later prioritize refresh, out
  of scope).
- No suggestion surfacing outside the profile (no feed, no notification).
- No person images/avatars.

## Impact

- **Backend**: CV client `get_person_volumes` + batch hydrate; creators
  package command + cache repo; migration 0018 (`creator_bibliography`
  + `creators.bibliography_fetched_at`); API sub-resource.
- **Coordination**: migration 0018 claimed — the keystore branch shifts
  to 0019 (noted for their rebase).
- **Frontend**: profile section + pending state + add hand-off; tests.
- **Docs**: manual Creators paragraph gains the More-from sentence;
  RISK-011 note; CHANGELOG v0.5.5.
- **Fixtures**: mock/unit fixtures mirror the live shapes probed above
  (stubs on person detail; hydration via the volumes filter), with the
  request paths pinned in client tests.

## Approval

Approved under the M4–M7 standing grant as amended 2026-07-11 (autonomous
run ends when M5 completes — this is the closing change; owner reviews
before M6). Gate obligations unchanged.
