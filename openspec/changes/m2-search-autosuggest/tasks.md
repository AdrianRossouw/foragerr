Work areas A, B, and C are parallelizable (separate file areas → separate
worktrees per FRG-PROC-008). Every requirement gets at least one tagged test
(FRG-PROC-004): pytest `@pytest.mark.req("FRG-...")`, vitest ID-in-test-name.

## A. Backend — ComicVine suggest variant (FRG-API-017)

- [x] A.1 `ComicVineClient.suggest_series(term)`: a single-page fetch (offset 0,
      limit ~10) reusing `search_series`'s filter-metacharacter neutralisation —
      NOT `_paginate` to `_max_pages`. Returns a bounded result carrying
      `complete` (no `truncated`). Tagged tests: at most one upstream page
      request per call (walk is never entered); metachar neutralisation; a
      mid-fetch upstream failure yields `complete=false`. [FRG-API-017]
- [x] A.2 `GET /api/v1/series/lookup/suggest?term=` route (registered BEFORE
      `/{series_id}`) → `suggest_series`, mapping `ComicVineAuthError` → 503 with
      `field="comicvine_api_key"` and the general `ComicVineError` → 503 backstop
      by REUSING the full lookup route's mapping (no parallel copy). `have_it`
      over the ≤10 ids retained; plausibility MAY be omitted. Response model
      `{records, complete}`. Tagged tests: auth failure → 503 + field
      discriminator + no key in body/log; clean page → `complete=true`; ~10-cap;
      the suggest envelope has no `truncated` field. [FRG-API-017]

## B. Frontend — Add Series autosuggest + header quick-search

- [x] B.1 Suggest API hook + fetcher wiring: term-keyed React Query for the
      suggest endpoint, ≥3-char gate, ~250 ms debounce, AbortSignal cancellation
      so superseded terms are discarded. Vitest: no request under 3 chars;
      debounced (not per-keystroke); a stale in-flight response resolved after a
      newer one does NOT overwrite it. [FRG-UI-005]
- [x] B.2 Add Series autosuggest dropdown: renders bounded suggest candidates,
      selecting one opens the SAME add panel as a full-lookup candidate, and a
      suggest 503 credential failure drives the same actionable "check ComicVine
      key in Settings" state (classified via `isComicVineAuthError`, not prose).
      Add Series reads a prefilled term on mount and seeds input + autosuggest.
      Vitest per the FRG-UI-005 delta scenarios (threshold, stale-discard,
      selection parity, auth state, prefill-on-mount). [FRG-UI-005]
- [x] B.3 Header quick-search component in `AppShell`: client-only fuzzy match
      over the cached `['series']` titles + aliases (in-repo matcher; a library
      choice is a SOUP delta — see D.2), ranked exact/prefix > word-boundary >
      subsequence, keyboard-navigable (arrows/Enter/Escape), selection → series
      detail route. Vitest: title+alias match with no network; keyboard nav +
      select; empty/loading cache degrades to fall-through only. [FRG-UI-019]
- [x] B.4 Always-present "Search ComicVine for '<term>'…" fall-through row →
      navigates to Add Series with the term prefilled (navigation state). Vitest:
      present even with local matches; carries the term into Add Series. [FRG-UI-019]

## C. e2e — deferred ch4 spine assertions (existing requirements)

- [x] C.1 Extend the Playwright/e2e harness on the assembled slice: seed a
      grab→import, then assert (a) the History screen shows the `grabbed` and
      `imported` rows sharing a downloadId, (b) the Wanted screen lists a known
      monitored/published/fileless issue, and (c) the OPDS Recent feed's
      acquisition link for the imported issue returns the file bytes. Tagged to
      the harness requirement and citing the feature IDs exercised — NO new IDs
      (these verify already-specified behaviour). [FRG-PROC-010, FRG-API-011,
      FRG-API-012, FRG-OPDS-013]

## D. Docs, security, traceability, gate

- [x] D.1 Manual (FRG-PROC-011): `docs/manual/user/web-ui.md` — Add Series section
      gains the debounced autosuggest behaviour; a new "Quick search" subsection
      documents the header search box (local titles/aliases, keyboard nav, and
      the "Search ComicVine for …" fall-through into Add Series). [FRG-PROC-011]
- [x] D.2 Security (FRG-PROC-006): `docs/security/` delta — STRIDE note on the new
      `/series/lookup/suggest` endpoint and its outbound request-amplification
      consideration, with the mitigations (≥3-char + debounce gating, single-page
      fetch, existing CV rate limiter); no new residual risk expected. If the
      fuzzy matcher adds a dependency, update `docs/security/soup-register.md` in
      the SAME change and keep `tools/soup_check.py` at exit 0 (default: no SOUP
      change). [FRG-PROC-006, FRG-PROC-012]
- [ ] D.3 Registry flips (FRG-API-017, FRG-UI-019 → implemented; FRG-UI-005 stays
      implemented) + traceability matrix regen + `tools/soup_check.py` exit 0.
      [FRG-PROC-004, FRG-PROC-005]
- [ ] D.4 Suites green (backend + frontend + e2e); pre-merge review cycle
      (`/code-review` + `/simplify`) + gate angles; fixes; archive; `--no-ff`
      merge with full suite green; main suites; tag. [FRG-PROC-007]
