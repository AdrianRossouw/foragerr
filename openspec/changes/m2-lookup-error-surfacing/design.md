# Design — m2-lookup-error-surfacing

## Context

`ComicVineClient._paginate` (metadata/comicvine.py) implements FRG-META-004's
partial-failure tolerance with a blanket `except ComicVineError` that flips
`complete=False` and stops the walk. `ComicVineAuthError` (raised by
`_raise_for_status` on 401/403 and `_raise_for_cv_error` on CV code 100) is a
subclass, so a missing/invalid key degrades to an empty `Page(complete=False)`.
`lookup_series` (api/series.py) returns `response_model=list[LookupCandidateResource]`,
dropping `complete` — so the UI receives `200 []`. `AddSeries.tsx` already has a
`lookup.isError` branch, but it can never fire for auth failures today; the empty
list renders "No volumes found".

## Goals / Non-Goals

**Goals:**
- Auth errors escape the pagination walk (typed, key never logged/echoed).
- Lookup response distinguishes error / incomplete / clean-empty.
- Add Series renders all three states distinctly, credential errors actionably.

**Non-Goals:**
- No settings "test key" button; no change to refresh/reconciliation's
  consumption of `complete=False`; no retry-policy changes (FRG-META-003).

## Decisions

1. **Carve-out location: `_paginate`'s except clause** — add
   `except ComicVineAuthError: raise` ahead of the general
   `except ComicVineError` (or `raise` from a guard inside it). All callers of
   `_paginate` (search, refresh syncs) get the propagation; refresh paths
   already handle `ComicVineError` at their own boundaries, and failing a sync
   loudly on a revoked key is more correct than recording an incomplete sync
   and retrying forever. Alternative considered: carve out only in
   `search_series` — rejected, leaves refresh syncs silently spinning on a
   dead credential.
2. **Lookup response becomes an envelope** —
   `LookupResponse { records: LookupCandidateResource[], complete: bool }`
   replacing the bare list. Breaking for the response shape, but the UI is the
   only consumer and changes in the same commit set. Alternative (custom
   response header for completeness) rejected as invisible-in-openapi.
3. **Auth mapping in the endpoint** — `except ComicVineAuthError` before the
   existing `except ComicVineError`, mapping to the existing
   `_COMICVINE_LOOKUP_ERROR_STATUS` (503) with a message naming the ComicVine
   API key ("ComicVine rejected the API key (missing or invalid) — set
   comicvine_api_key"). Message is static — never interpolates the key; the
   client's typed errors already scrub `api_key` params from messages
   (FRG-META-002). A distinct status (401/502) was considered; 503 keeps the
   existing "upstream unavailable" contract and the UI keys off the message,
   not the code — revisit if a programmatic consumer ever needs to distinguish.
4. **Frontend**: `useLookup` fetches the envelope; `AddSeries` branches on
   query error (inspect the API error message for the credential case → render
   "check Settings" guidance), `complete=false` (render candidates + an
   "incomplete results" notice), and `complete=true && records.length===0`
   (existing "No volumes found"). The generic fetch-error branch stays for
   network/other failures.

## Risks / Trade-offs

- [Auth propagation reaches refresh/sync callers] → survey `ComicVineError`
  handling at those boundaries in the impl task; they already catch the parent
  type, so behavior change is "incomplete sync" → "failed sync", which is the
  desired loud failure. Tests must cover one refresh path with an auth error.
- [Response-shape change breaks stale open tabs] → acceptable pre-release;
  UI and API ship together.
- [UI sniffing the error message string is brittle] → confine the sniff to one
  helper with a test; the API message text is asserted by a backend test so
  drift is caught.

## Migration Plan

Single deploy; no data migration. Rollback = revert the merge commit.

## Open Questions

None.
