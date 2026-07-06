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
   `_paginate` (search, refresh syncs) get the propagation. Boundary survey
   (review-verified): `refresh_series` has no ComicVine-specific catch of its
   own — an auth error propagates to the command worker's generic handler,
   which marks the command failed and releases its exclusivity group; the
   downstream scan/monitor chain does not run. That loud failure is the
   intended behavior — more correct than recording an incomplete sync and
   retrying forever on a dead credential. Alternative considered: carve out
   only in `search_series` — rejected, leaves refresh syncs silently spinning.
2. **Lookup response becomes an envelope** —
   `LookupResponse { records: LookupCandidateResource[], complete: bool,
   truncated: bool }` replacing the bare list. `truncated` is carried
   separately from `complete` because the two demand opposite user guidance
   (cap hit → narrow the term; degrade → retry). Breaking for the response
   shape, but the UI is the only consumer and changes in the same commit set.
   Alternative (custom response header for completeness) rejected as
   invisible-in-openapi. Version-skew note: an old backend serving a bare
   array to a new frontend is accepted (single-deploy, pre-release).
3. **Auth mapping in the endpoint** — `except ComicVineAuthError` before the
   existing `except ComicVineError`, mapping to the existing
   `_COMICVINE_LOOKUP_ERROR_STATUS` (503) with a message naming the ComicVine
   API key ("ComicVine rejected the API key (missing or invalid) — set
   comicvine_api_key") AND `field="comicvine_api_key"` on the ApiError so the
   errors[] entry is a machine-readable discriminator (the same channel
   FRG-API-002 gives download-client validation errors). A warning is logged
   (static text, no key material). Message stays static — never interpolates
   the key; the client's typed errors already scrub `api_key` params
   (FRG-META-002). 503 (not 401/502) keeps the existing "upstream unavailable"
   contract for this endpoint.
4. **Frontend**: `useLookup` fetches the envelope; `AddSeries` renders exactly
   one outcome state, classified structurally, in precedence order: credential
   error (detected via `error.body.errors[0].field === "comicvine_api_key"` —
   a helper in the api layer, NOT message-prose sniffing, which drifts and
   false-positives) → generic lookup error → degraded-with-zero-records
   (error styling + retry guidance) → truncated notice ("narrow your search")
   → incomplete notice (candidates render) → complete-and-empty "No volumes
   found" → candidates. Retryability: a same-term re-submit must issue a fresh
   request — successful complete lookups may stay cached (`staleTime`
   Infinity), but error/incomplete/truncated outcomes are refetched on submit
   (explicit `refetch()` on identity term, or outcome-dependent staleTime).
5. **Add flow parity** — `add_series`'s ComicVine existence check catches
   `ComicVineAuthError` distinctly and surfaces the same credential wording,
   so the failure the lookup made actionable does not regress to a generic
   "could not be fetched" one click later.

## Risks / Trade-offs

- [Auth propagation reaches refresh/sync callers] → surveyed: refresh flows have
  no ComicVine-specific boundary of their own — the error reaches the command
  worker's failure handling (command marked failed, locks released, downstream
  chain skipped), which is the desired loud failure. A refresh auth-failure
  test pins it.
- [Response-shape change breaks stale open tabs / skewed deploys] →
  acceptable pre-release; UI and API ship together in one image.
- [Field-based error discriminator couples UI to the errors[] envelope shape]
  → that envelope is already the FRG-API-002 contract other screens consume
  (download-client validation does the same); a backend test asserts the field
  value verbatim.

## Migration Plan

Single deploy; no data migration. Rollback = revert the merge commit.

## Open Questions

None.
