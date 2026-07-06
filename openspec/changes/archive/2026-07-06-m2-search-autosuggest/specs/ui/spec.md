# ui — delta for m2-search-autosuggest

## ADDED Requirements

### Requirement: FRG-UI-019 — Global header quick-search over the local library

The UI SHALL provide a search box in the application header that fuzzy-matches
the user's query against the LOCAL library's series titles AND aliases using data
already cached on the client (the `['series']` index query), issuing NO network
request per keystroke. The results list SHALL be keyboard-navigable (arrow keys
move the active result, Enter selects it, Escape closes the list); selecting a
matched series SHALL navigate to that series' detail page. The results SHALL
always include, as the final row, a "Search ComicVine for '<term>'…" fall-through
that navigates to the Add Series screen with the term prefilled — present even
when local matches exist, so the remote-add escape hatch is never hidden.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.4 (global "go to series" affordance);
  mylar-feature-surface.md §SER (search-then-add bridge); FRG-UI-001 (client
  state via React Query — the cached `['series']` index is the match source),
  FRG-UI-005 (the Add Series screen the fall-through routes into).
- **Notes**: Purely client-side matching over already-delivered data (the series
  index resource already carries `aliases`), so there is no per-keystroke server
  load and no new API. Ranking is exact/prefix > word-boundary > subsequence,
  casefolded. When the `['series']` cache is empty or still loading, the box
  degrades to only the fall-through row rather than erroring. The fall-through
  carries the term into Add Series via navigation state, which seeds that
  screen's input and its debounced autosuggest (FRG-UI-005). No new SOUP is
  expected for the matcher; a library choice would trigger a SOUP-register delta.

#### Scenario: Local titles and aliases match without a network call

- **WHEN** the user types into the header search box and a series whose title OR
  one of whose aliases fuzzy-matches the term exists in the cached library index
- **THEN** that series appears in the results list ranked by match quality, and
  no network request is issued for the keystrokes (matching runs entirely over
  the client-cached `['series']` data)

#### Scenario: Keyboard navigation and selection

- **WHEN** results are shown and the user presses the down/up arrows and then
  Enter
- **THEN** the active result moves with the arrows, Enter navigates to the active
  series' detail page, and Escape closes the results list without navigating

#### Scenario: Fall-through to ComicVine add is always present

- **WHEN** the results list renders, whether or not any local series matched
- **THEN** its final row is "Search ComicVine for '<term>'…", and activating it
  navigates to the Add Series screen with the typed term prefilled (seeding that
  screen's search input), bridging a local miss to a remote add

#### Scenario: Empty or loading cache degrades gracefully

- **WHEN** the `['series']` index is empty or still loading and the user types a
  term
- **THEN** the box shows only the "Search ComicVine for '<term>'…" fall-through
  row (no error, no spinner masquerading as results), so the add bridge still
  works before the library index has loaded

## MODIFIED Requirements

### Requirement: FRG-UI-005 — Add-series search screen

The UI SHALL provide an add-series screen where the user searches ComicVine by
title (or pastes a ComicVine volume id/URL), sees candidate volumes with poster,
year, publisher, and issue count, and adds one with root folder, monitoring
strategy, and format-profile selections. As the user types a title, the screen
SHALL offer a debounced ComicVine autosuggest dropdown backed by the bounded
suggest endpoint (FRG-API-017): it fires only when the trimmed term is at least
three characters, is debounced, and is cancellable so that a response for a
superseded term is discarded and never rendered; selecting a suggestion behaves
exactly like selecting a full-lookup candidate (it opens the same add panel). The
autosuggest is an accelerator over — and never replaces — the full-lookup submit
path: the screen SHALL still distinguish the non-success search outcomes — a
lookup error (including ComicVine credential failure, classified by the API's
machine-readable field discriminator and rendered with guidance to check
Settings), an incomplete result (degraded walk), a capped result (advising a
narrower search), and a genuinely empty result — never rendering an error,
degraded, or capped outcome as plain "no results", rendering exactly one outcome
state at a time, and always honouring a re-submitted search (a same-term retry
issues a fresh lookup rather than serving the failed or degraded result from
cache). A ComicVine credential failure from the autosuggest SHALL drive the same
actionable "check the ComicVine key in Settings" state as the full lookup, via
the same field discriminator.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (AddSeries lookup + as-you-type
  suggestion), §1.2 add flow; mylar-feature-surface.md §SER (add by CV search or
  CV ID); m2-search-autosuggest (debounced suggest accelerator).
- **Notes**: First leg of the vertical slice. "Import existing library" mass-add
  flow is a separate M2 requirement — keep them distinct. Outcome-state
  distinction added in m2-lookup-error-surfacing: a missing/invalid ComicVine key
  previously rendered as "no results". m2-search-autosuggest: the autosuggest is
  a passive accelerator riding FRG-API-017 (first-page-only) — the full-lookup
  submit path with its incomplete/truncated/empty outcome states is unchanged and
  remains the authoritative search; the header quick-search (FRG-UI-019) can seed
  this screen's input via a prefilled term.

#### Scenario: Debounced autosuggest fires only past the character threshold

- **WHEN** the user types a title into the add-series search input
- **THEN** no autosuggest request is issued until the trimmed term is at least
  three characters, the request is debounced (not one per keystroke), and the
  dropdown renders bounded ComicVine candidates from the suggest endpoint

#### Scenario: Stale autosuggest responses are discarded

- **WHEN** the user types further characters (superseding an earlier term) while
  an earlier autosuggest request is still in flight
- **THEN** the earlier request is cancelled or its response discarded, so only
  the latest term's suggestions can render — a slow stale response never
  overwrites newer suggestions

#### Scenario: Selecting a suggestion opens the add panel like a full candidate

- **WHEN** the user selects an entry from the autosuggest dropdown
- **THEN** the same add panel opens as when selecting a full-lookup candidate
  (root folder, format profile, monitor strategy, search-on-add), with no
  divergent add path

#### Scenario: Autosuggest credential failure reuses the actionable error state

- **WHEN** an autosuggest request fails because the ComicVine API key is missing
  or invalid (the suggest endpoint's 503 with `field="comicvine_api_key"`)
- **THEN** the screen renders the same actionable state that names the ComicVine
  API key as the likely cause and points at Settings — classified by the field
  discriminator, not by message prose, and not as an empty "no results" dropdown

#### Scenario: Search renders CV candidates with plausibility annotations

- **WHEN** the user types a title and the ComicVine lookup returns candidates
- **THEN** each candidate renders poster, year, publisher, and issue count, and
  any plausibility annotations returned are rendered on the candidate

#### Scenario: Credential failure renders an actionable error, not empty results

- **WHEN** the lookup request fails because the ComicVine API key is missing or
  invalid
- **THEN** the screen renders an error state that names the ComicVine API key as
  the likely cause and points the user at Settings — the empty "no results"
  presentation is not shown

#### Scenario: Incomplete results are flagged; clean empty stays plain

- **WHEN** the lookup succeeds but the response is marked incomplete
- **THEN** any returned candidates render along with a notice that results may be
  incomplete and a retry may recover the rest; a degraded response with ZERO
  candidates renders as a lookup failure (error styling, retry guidance), not as
  a mild footnote; a complete response with zero candidates renders the plain "no
  results" state

#### Scenario: Capped results advise narrowing, not retrying

- **WHEN** the lookup response is marked truncated (the deliberate result cap was
  hit)
- **THEN** the returned candidates render with a notice that the result set was
  capped and the search should be narrowed — not the transient "retry"
  incomplete wording

#### Scenario: Re-searching the same term retries for real

- **WHEN** a previous search for a term ended in an error, an incomplete result,
  or a capped result, and the user submits the same term again
- **THEN** a fresh lookup request is issued (the failed/degraded outcome is not
  served from cache), so recovering after fixing the API key or after a ComicVine
  hiccup requires no term perturbation

#### Scenario: Add panel exposes required add options

- **WHEN** the user selects a candidate
- **THEN** the add panel renders controls for root folder, format profile,
  monitor strategy, and search-on-add

#### Scenario: Adding navigates to detail with refresh command visible

- **WHEN** the user confirms the add
- **THEN** the app navigates to the new series' detail route and a refresh command
  is visible as in-progress on that screen

#### Scenario: A prefilled term seeds the search on mount

- **WHEN** the Add Series screen is opened with a term prefilled (e.g. from the
  header quick-search fall-through)
- **THEN** the search input is seeded with that term and the debounced autosuggest
  runs for it on mount, so the local-miss → remote-add handoff lands the user in
  a live search
