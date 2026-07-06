## Why

M2 change 4 (m2-daily-surfaces) delivered the review screens but left two
day-to-day navigation gaps and one deferred verification debt:

1. **Add Series is a submit-then-wait form.** Finding a volume means typing a
   full term, submitting, and waiting for the whole ComicVine pagination walk —
   no as-you-type feedback, so a mistyped or ambiguous term costs a full round
   trip. Every other Sonarr-shaped add screen suggests candidates while you
   type.
2. **There is no way to jump to a series you already own.** With a growing
   library the only path to a series' detail page is scrolling the index or
   using the browser. There is no global "go to" affordance, and no bridge from
   "I searched my library and it isn't here" to "add it from ComicVine".
3. **The ch4 e2e harness proves first-run registration but not the daily
   spine.** m2-daily-surfaces explicitly deferred three end-to-end spine
   assertions to this change (History shows the grab→import chain, Wanted lists
   a missing issue, OPDS Recent serves the imported file). Requirement evidence
   for those behaviours already exists via tagged backend/frontend tests; this
   change pays down the deferred *integration* coverage so the assembled slice
   is exercised through the real UI/feed, not only in isolation.

## What Changes

- **ComicVine suggest — bounded lookup variant (FRG-API-017, NEW)**: a new
  `GET /api/v1/series/lookup/suggest?term=` that fetches only the FIRST page of
  ComicVine volume results (~10 candidates) and NEVER performs the full
  pagination walk that `/series/lookup` does. It reuses the existing outbound
  ComicVine integration and the same filter-metacharacter neutralisation, and
  it honours the SAME error contract as the full lookup: a credential failure
  returns HTTP 503 with `errors[0].field="comicvine_api_key"` (never a `200`
  empty list), so the frontend's existing `isComicVineAuthError` classifier
  works unchanged. The suggest envelope carries `complete` (a mid-fetch degrade
  is distinguishable from a clean empty) but no `truncated` flag — partiality is
  the endpoint's defining property (there is always "more" behind the full
  lookup), so a cap is not a truncation to signal.

- **Add Series autosuggest (MODIFIED FRG-UI-005)**: the add-series screen gains
  a debounced autosuggest dropdown backed by FRG-API-017 — it fires only after
  ≥3 typed characters, is debounced, and is cancellable so that stale responses
  for superseded terms are discarded and never render. The autosuggest is an
  accelerator over the existing full-lookup submit path (which keeps its richer
  outcome-state handling); selecting a suggestion behaves exactly like selecting
  a full-lookup candidate. The same 503 credential-failure contract drives the
  same actionable error state as the full lookup.

- **Global header quick-search over the LOCAL library (FRG-UI-019, NEW)**: a
  search box in the app header that fuzzy-matches over the LOCAL series titles
  AND aliases already cached client-side (the `['series']` React Query index),
  with NO network request per keystroke. It is keyboard-navigable (arrow keys,
  Enter, Escape); selecting a result navigates to that series' detail page. A
  final "Search ComicVine for '<term>'…" fall-through row is always present and
  routes to the Add Series screen (FRG-UI-005) with the term prefilled, bridging
  local-miss → remote-add.

- **e2e spine assertions (existing FRG-API-011, FRG-API-012, FRG-OPDS-013 under
  FRG-PROC-010)**: extend the Playwright/e2e harness so the assembled slice
  asserts (a) History shows the grab→import event chain, (b) Wanted lists a
  missing issue, and (c) OPDS Recent actually serves the imported file's bytes.
  No new requirement IDs — these assert already-specified behaviour; they close
  the coverage the ch4 tasks deferred here.

## Capabilities

### New Capabilities

- `api`: FRG-API-017 (ComicVine suggest — bounded, cheap, cancellable first-page
  lookup variant).
- `ui`: FRG-UI-019 (global header quick-search over the local library).

### Modified Capabilities

- `ui`: FRG-UI-005 (add-series screen elaborated with debounced, cancellable
  ComicVine autosuggest as an accelerator over the existing submit path).

## Impact

- **Code**: backend — new `suggest_series` bounded fetch on the ComicVine client
  (single page, no full walk) + a new `/series/lookup/suggest` route reusing the
  lookup's auth/error mapping; frontend — Add Series autosuggest control + hook,
  a new header quick-search component in `AppShell` reading the `['series']`
  cache, a client-side fuzzy matcher, and a term-prefill bridge into Add Series;
  e2e — extended harness assertions over History/Wanted/OPDS-Recent.
- **DB**: none (no new tables or columns; suggest is a read against ComicVine,
  quick-search is purely client-side over cached data).
- **Security docs** (FRG-PROC-006): the suggest variant is the SAME outbound
  ComicVine integration as the full lookup — no new listener, and no new parser
  of untrusted input beyond what lookup already sanitises (CV filter
  metacharacters are already neutralised). It IS, however, a NEW query-string
  endpoint whose whole point is to be called frequently as the user types, so it
  raises a request-amplification / outbound-DoS consideration on the CV
  integration. That is bounded by three existing/added controls (client-side
  ≥3-char + debounce gating, a single-page server fetch instead of the full
  walk, and the existing CV client rate limiter). This warrants a SMALL
  `docs/security/` delta (STRIDE note on the new endpoint + amplification
  mitigation; no new residual risk expected), recorded in this same change as a
  closing task. The header quick-search adds NO attack surface (client-only over
  data already delivered). **Declared: a security-docs delta IS required and is
  a task in this change.**
- **Manual** (FRG-PROC-011): this adds user-facing search UX, so
  `docs/manual/user/web-ui.md` WILL be updated — the Add Series section gains the
  autosuggest behaviour, and a new "Quick search" subsection documents the header
  search box (local-only matching over titles/aliases, keyboard navigation, and
  the "Search ComicVine for …" fall-through into Add Series). No admin-facing or
  OPDS manual change (the e2e work is internal verification, not user behaviour).
- **Dependencies / SOUP** (FRG-PROC-012): none anticipated — the fuzzy matcher
  is intended to be a small in-repo helper, not a new dependency. If
  implementation elects to add a fuzzy-match library, `docs/security/soup-register.md`
  must be updated in the same change (called out in the closing tasks); the
  default expectation is no SOUP change and `tools/soup_check.py` exits 0.

## Non-goals

- No server-side search index or search API over the local library (the header
  search is deliberately client-only over the already-cached `['series']` set;
  a server search endpoint is out of scope unless the cached set stops being the
  source of truth).
- No autosuggest on any screen other than Add Series.
- No change to the full `/series/lookup` walk, its `truncated`/`complete`
  semantics, or its plausibility annotations.
- No new requirement IDs for the e2e assertions — they verify existing
  requirements.
- No caching/persistence of ComicVine suggest results beyond React Query's
  in-memory term-keyed cache.

## Approval

Adrian pre-approved this change on 2026-07-06 under the M2/M3 standing
FRG-PROC-009 grant. His words, verbatim:

> keep going with m2/m3 and all their related changes as you go. I'll come check in later

Recorded per the M1-style standing-grant model; m2-search-autosuggest (M2 change
4.5) falls squarely within that grant's scope.
