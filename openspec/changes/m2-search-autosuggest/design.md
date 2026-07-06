# Design — m2-search-autosuggest

## Context

Grounding (research-verified against the current tree):

- `GET /api/v1/series/lookup` (`api/series.py::lookup_series`) runs
  `ComicVineClient.search_series(term)`, which walks up to `_max_pages` bounded
  by `_search_cap` via `_paginate`, and returns a `SearchResult` with
  `complete`/`truncated`. The route maps `ComicVineAuthError` → HTTP 503 with a
  static message and `field="comicvine_api_key"`; every other per-page
  `ComicVineError` is swallowed and degrades to `complete=False` (a mid-walk
  outage is a `200` with `complete=false`, NOT a 503). `search_series`
  neutralises CV filter metacharacters (`,` and `:`) before building the filter.
- The `LookupResponse` envelope is `{records, complete, truncated}`. The
  frontend classifies auth failures with `isComicVineAuthError`
  (`frontend/src/api/fetcher.tsx`) by looking for `errors[].field ===
  'comicvine_api_key'` — prose-independent.
- The series index resource (`GET /api/v1/series`, `['series']` React Query key,
  `useLibraryIndex`/`useSeriesList`) already carries `aliases: string[]` per row
  (`api/series.py` SeriesResource, `frontend/src/api/types.ts`). So a client-side
  quick-search over titles AND aliases needs NO new endpoint — the data is
  already delivered.
- The app header/chrome lives in `frontend/src/components/AppShell`.

## Goals / Non-Goals

**Goals:** a cheap, cancellable ComicVine suggest endpoint; debounced Add Series
autosuggest riding it; a client-only header quick-search over the local library
with a remote-add fall-through; the three deferred e2e spine assertions.

**Non-Goals:** server-side local search; autosuggest elsewhere; changes to the
full lookup walk; new SOUP; persisting suggest results.

## Decisions

1. **Dedicated suggest route, not a mode flag on `/lookup`.**
   `GET /api/v1/series/lookup/suggest?term=` (registered BEFORE `/{series_id}`
   like `/lookup`, so an int path param never swallows it). Rationale: the
   suggest response model differs (`{records, complete}` — no `truncated`, see
   #3), it wants its own React Query key and short cache lifetime, and a
   dedicated path keeps the full lookup's contract byte-for-byte unchanged.
   Alternative (a `?suggest=true` param on `/lookup`) rejected: it would overload
   one response model with two envelope shapes and muddy caching.

2. **Bounded fetch: first page only, never the walk.** A new
   `ComicVineClient.suggest_series(term)` fetches a SINGLE page (offset 0,
   `limit ≈ 10`) rather than looping `_paginate` to `_max_pages`. It reuses the
   exact same filter-metacharacter neutralisation as `search_series` so the
   injection posture is identical. It MAY skip the plausibility scoring the full
   search does, to stay cheap — suggest candidates need only name, start year,
   publisher, issue count, cv_volume_id, and image_url. The `have_it` annotation
   (one cheap `IN` query over ≤10 ids) is retained for parity with lookup so a
   suggestion for an already-owned volume can be marked. This is the load-bearing
   "NEVER the full pagination walk" guarantee — it gets a tagged test that
   asserts at most one upstream page request per suggest call.

3. **Suggest envelope carries `complete` but NOT `truncated`.** The full lookup
   distinguishes a deliberate cap (`truncated=true`, "narrow the term") from a
   transient degrade (`complete=false`, "retry may help"). Suggest is
   *definitionally* partial — there is always more behind the full lookup — so a
   cap is not a signal-worthy truncation. It keeps `complete` only: a single-page
   fetch that fails mid-flight is `complete=false` (the dropdown can show a quiet
   "couldn't reach ComicVine" affordance), a clean page is `complete=true`. This
   keeps the envelope honest without inventing a "truncated is always true"
   field that carries no information.

4. **Same error contract as the full lookup, reused verbatim.** The suggest route
   maps `ComicVineAuthError` → HTTP 503 with the SAME static message and
   `field="comicvine_api_key"`, and the general `ComicVineError` arm to a 503
   backstop — reusing the lookup route's mapping code, not a parallel copy. This
   is what lets the frontend's existing `isComicVineAuthError` work unchanged and
   drive the same actionable "check your ComicVine key in Settings" state.

5. **Debounce + cancellation live on the frontend.** The Add Series autosuggest
   fires only when the trimmed term is ≥3 characters, debounced (~250 ms), and
   keyed by term in React Query so only the latest term's data can render.
   In-flight requests for a superseded term are aborted (AbortSignal wired
   through the fetcher) so a slow stale response can never overwrite a newer one.
   The endpoint stays a passive accelerator: the existing full-lookup submit path
   (with its rich incomplete/truncated/empty outcome states) is untouched and
   remains the authoritative search. Selecting a suggestion reuses the existing
   candidate-selection → add-panel flow (no divergent add path).

6. **Header quick-search is client-only over the `['series']` cache.** No network
   per keystroke. The matcher reads the already-cached series index (titles +
   `aliases`) and ranks matches: exact/prefix > word-boundary > subsequence
   (casefolded, whitespace-normalised). A small in-repo helper — NOT a new SOUP
   dependency (if implementation wants a library, that is a SOUP delta, called
   out in tasks). The list is keyboard-navigable (ArrowUp/Down move the active
   row, Enter selects, Escape closes); selecting a series navigates to
   `['series', id]`'s detail route. If the `['series']` cache is empty/loading,
   the box degrades to only the fall-through row (below) rather than erroring.

7. **The "Search ComicVine for '<term>'…" fall-through.** Always rendered as the
   final row of the quick-search results, regardless of how many local matches
   exist (so a local hit never hides the escape hatch). Activating it navigates
   to the Add Series screen with the term prefilled — carried as a route param /
   navigation state that Add Series reads on mount to seed both its input and,
   via #5, its debounced autosuggest. This is the local-miss → remote-add bridge;
   it does NOT itself call ComicVine (Add Series owns that once it mounts).

8. **e2e spine approach: assert through the real UI/feed on the assembled slice.**
   Extend the existing Playwright/e2e harness (the same one ch4 pointed at the
   real root-folder API) to drive a seeded grab→import and then assert: (a) the
   History screen renders the `grabbed` and `imported` rows sharing a downloadId
   (FRG-API-011 / FRG-UI-010 surface); (b) the Wanted screen lists a known
   monitored, published, fileless issue (FRG-API-012 / FRG-UI-011); (c) the OPDS
   Recent feed's acquisition link for the imported issue actually returns the
   file bytes (FRG-OPDS-013 / FRG-OPDS-005). These are additional integration
   assertions tagged to FRG-PROC-010 (the harness requirement) and cite the
   feature IDs they exercise; they add NO new requirement IDs because the
   behaviours are already specified and already have tagged unit/component tests.

## Risks / Trade-offs

- **[Suggest amplifies outbound ComicVine calls]** → bounded on three sides:
  client ≥3-char + debounce gating, a single-page server fetch (not the walk),
  and the existing CV client rate limiter (FRG-META-003). Security-docs delta
  records this explicitly. No new residual risk expected.
- **[Stale suggest response overwrites a newer term]** → term-keyed React Query
  cache + AbortSignal cancellation make only the latest term renderable; pinned
  by a frontend test that resolves an older request after a newer one and asserts
  the newer wins.
- **[Client fuzzy match is O(n) per keystroke over the whole library]** →
  acceptable at single-user library scale (hundreds–low-thousands of series);
  the match is a cheap string scan over already-in-memory data, memoised on the
  cached list + term. Revisit only if profiling shows jank.
- **[Fall-through hidden when there are many local matches]** → deliberately
  always-rendered as the final row; covered by a test asserting it appears even
  with local hits present.

## Migration Plan

No migrations. No schema change. Rollback = revert the merge; the suggest route
and header control are additive and independent of existing surfaces.

## Open Questions

None blocking. Two implementation-time calls, both with a stated default:
(1) exact debounce interval — default 250 ms, tune if it feels laggy;
(2) whether the fuzzy matcher stays in-repo — default yes (no SOUP); any library
choice triggers the SOUP-register task.
