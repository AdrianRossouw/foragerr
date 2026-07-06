## Why

User-reported defect (Adrian, 2026-07-06, first hands-on UI test): searching for a
comic under Add Series silently shows "no results" when the ComicVine API key is
missing or invalid. The client's pagination walk (FRG-META-004 partial-failure
tolerance) catches *every* per-page `ComicVineError` — including
`ComicVineAuthError` — and degrades to an empty `SearchResult` with
`complete=False`; `GET /api/v1/series/lookup` then drops the `complete` flag and
returns `200 []`. An unconfigured or revoked key is therefore indistinguishable
from a genuinely empty search, both at the API and in the UI. Auth failure is not
a transient page failure: an invalid key cannot succeed on a later page, so
degrading it to a partial result is wrong even under FRG-META-004's own rationale.

## What Changes

- `ComicVineClient` pagination: `ComicVineAuthError` (HTTP 401/403, ComicVine
  error code 100) propagates out of the offset walk instead of being absorbed
  into a partial/empty result. All other `ComicVineError`s keep the existing
  degrade-to-`complete=False` behavior.
- `GET /api/v1/series/lookup`: maps `ComicVineAuthError` to a distinct
  client-visible error response (502-class with a message naming the ComicVine
  credential, never echoing the key). The response model additionally exposes the
  walk's `complete` flag so a degraded partial result is distinguishable from a
  clean empty result.
- Add Series screen: renders an explicit error state ("ComicVine API key missing
  or invalid — check Settings") on lookup auth failure instead of the empty
  "no results" state, and a lighter "results may be incomplete" notice when the
  lookup returns `complete=false`.
- Tests tagged `FRG-META-004`, `FRG-API-003`, `FRG-UI-005` cover the new
  scenarios (pytest `@pytest.mark.req`, vitest name tags).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `meta`: FRG-META-004 — pagination partial-failure tolerance carves out auth
  errors: they propagate instead of degrading to `complete=False`.
- `api`: FRG-API-003 — lookup endpoint surfaces auth failure as an error response
  and exposes result completeness; empty-and-complete stays `200 []`.
- `ui`: FRG-UI-005 — Add Series search distinguishes error / incomplete / empty
  states.

## Impact

- **Code**: `backend/src/foragerr/metadata/comicvine.py` (`_paginate`),
  `backend/src/foragerr/api/series.py` (`lookup_series`, response envelope),
  `frontend/src/screens/add/AddSeries.tsx` + `frontend/src/api/hooks.ts`;
  matching backend/frontend tests.
- **API consumers**: lookup response gains a completeness field (additive);
  auth failure changes from `200 []` to an error status — the UI is the only
  consumer and is updated in the same change.
- **Security docs**: none — no new attack surface (no new listener, parser of
  untrusted input, credential, or outbound integration; the error path must not
  echo the API key, which existing FRG-META-002 log-hygiene tests already
  guard).
- **Manual** (FRG-PROC-011): troubleshooting section gains a "series search
  returns nothing / credential errors" entry; Add Series section notes the new
  error states.
- **Dependencies / SOUP**: none.

## Non-goals

- No settings-screen "test ComicVine key" button (candidate for M2
  ops-health-backups' health checks, or later).
- No change to how refresh/reconciliation syncs consume `complete=False`
  (FRG-META-008 behavior unchanged).
- No retry/backoff changes for rate-limit or transient errors (FRG-META-003
  unchanged).

## Approval

Covered by Adrian's standing FRG-PROC-009 grant of 2026-07-06 ("keep going with
m2/m3 and all their related changes as you go. I'll come check in later"),
which extends to defect-fix changes arising from M2 testing. The triggering
defect was reported by Adrian directly in-session on 2026-07-06.
