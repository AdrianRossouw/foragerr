# ui — delta for m4-add-new

## MODIFIED Requirements

### Requirement: FRG-UI-005 — Add-series search screen

The UI SHALL provide an add-series screen where the user searches ComicVine by title (or pastes a ComicVine volume id/URL), sees candidate volumes as expandable result cards per the M4 design handoff — cover, name, year, publisher, issue count, a short description/deck, and an "In library" badge when already present — in the relevance order the API returns (FRG-META-015), and adds one through an inline add-config panel with root folder, format-profile, monitoring-strategy, search-on-add, and collect-as (single issues / collected editions) controls. As the user types a title, the screen SHALL offer a debounced ComicVine autosuggest dropdown backed by the bounded suggest endpoint (FRG-API-017): it fires only when the trimmed term is at least three characters, is debounced, and is cancellable so that a response for a superseded term is discarded and never rendered; selecting a suggestion behaves exactly like selecting a full-lookup candidate (it opens the same add panel). The autosuggest is an accelerator over — and never replaces — the full-lookup submit path: the screen SHALL still distinguish the non-success search outcomes — a lookup error (including ComicVine credential failure, classified by the API's machine-readable field discriminator and rendered with guidance to check Settings), an incomplete result (degraded walk), a capped result (advising a narrower search), and a genuinely empty result — never rendering an error, degraded, or capped outcome as plain "no results", rendering exactly one outcome state at a time, and always honouring a re-submitted search (a same-term retry issues a fresh lookup rather than serving the failed or degraded result from cache). A ComicVine credential failure from the autosuggest SHALL drive the same actionable "check the ComicVine key in Settings" state as the full lookup, via the same field discriminator.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (AddSeries lookup + as-you-type suggestion), §1.2 add flow; mylar-feature-surface.md §SER (add by CV search or CV ID); m2-search-autosuggest (debounced suggest accelerator); design handoff §3 add-new (m4-add-new).
- **Notes**: First leg of the vertical slice. "Import existing library" mass-add flow is a separate M2 requirement — keep them distinct. Outcome-state distinction added in m2-lookup-error-surfacing: a missing/invalid ComicVine key previously rendered as "no results". m2-search-autosuggest: the autosuggest is a passive accelerator riding FRG-API-017 (first-page-only) — the full-lookup submit path with its incomplete/truncated/empty outcome states is unchanged and remains the authoritative search; the header quick-search (FRG-UI-019) can seed this screen's input via a prefilled term. m4-add-new: visuals rebuilt to the design handoff (expandable cards, inline panel, monitor as a segmented control); plausibility chips give way to the ranked order plus the "In library" badge, with the signals still available on the candidate payload. The collect-as control is untouched by default (title-cue derivation applies, FRG-SER-018); an explicit choice maps to the locked add-time book-type (collected editions → `tpb`, refinable to gn/hc later on the series).

#### Scenario: Debounced autosuggest fires only past the character threshold

- **WHEN** the user types a title into the add-series search input
- **THEN** no autosuggest request is issued until the trimmed term is at least three characters, the request is debounced (not one per keystroke), and the dropdown renders bounded ComicVine candidates from the suggest endpoint

#### Scenario: Stale autosuggest responses are discarded

- **WHEN** the user types further characters (superseding an earlier term) while an earlier autosuggest request is still in flight
- **THEN** the earlier request is cancelled or its response discarded, so only the latest term's suggestions can render — a slow stale response never overwrites newer suggestions

#### Scenario: Selecting a suggestion opens the add panel like a full candidate

- **WHEN** the user selects an entry from the autosuggest dropdown
- **THEN** the same add panel opens as when selecting a full-lookup candidate (root folder, format profile, monitor strategy, search-on-add, collect-as), with no divergent add path

#### Scenario: Autosuggest credential failure reuses the actionable error state

- **WHEN** an autosuggest request fails because the ComicVine API key is missing or invalid (the suggest endpoint's 503 with `field="comicvine_api_key"`)
- **THEN** the screen renders the same actionable state that names the ComicVine API key as the likely cause and points at Settings — classified by the field discriminator, not by message prose, and not as an empty "no results" dropdown

#### Scenario: Search renders CV candidates as design-handoff result cards

- **WHEN** the user types a title and the ComicVine lookup returns candidates
- **THEN** each candidate renders as a result card with cover, name, year, publisher, issue count, and description/deck, an "In library" badge when the series is already present, in the API's relevance order (FRG-META-015) without client-side reordering

#### Scenario: Credential failure renders an actionable error, not empty results

- **WHEN** the lookup request fails because the ComicVine API key is missing or invalid
- **THEN** the screen renders an error state that names the ComicVine API key as the likely cause and points the user at Settings — the empty "no results" presentation is not shown

#### Scenario: Incomplete results are flagged; clean empty stays plain

- **WHEN** the lookup succeeds but the response is marked incomplete
- **THEN** any returned candidates render along with a notice that results may be incomplete and a retry may recover the rest; a degraded response with ZERO candidates renders as a lookup failure (error styling, retry guidance), not as a mild footnote; a complete response with zero candidates renders the plain "no results" state

#### Scenario: Capped results advise narrowing, not retrying

- **WHEN** the lookup response is marked truncated (the deliberate result cap was hit)
- **THEN** the returned candidates render with a notice that the result set was capped and the search should be narrowed — not the transient "retry" incomplete wording

#### Scenario: Re-searching the same term retries for real

- **WHEN** a previous search for a term ended in an error, an incomplete result, or a capped result, and the user submits the same term again
- **THEN** a fresh lookup request is issued (the failed/degraded outcome is not served from cache), so recovering after fixing the API key or after a ComicVine hiccup requires no term perturbation

#### Scenario: Add panel exposes required add options

- **WHEN** the user selects a candidate
- **THEN** the inline add-config panel renders controls for root folder, format profile, monitor strategy (segmented), search-on-add, and collect-as (single issues / collected editions)

#### Scenario: Collect-as left untouched preserves derivation

- **WHEN** the user adds a series without touching the collect-as control
- **THEN** the add request carries no explicit book-type and the series is typed by title-cue derivation exactly as before (FRG-SER-018); an explicit choice sends the corresponding locked book-type

#### Scenario: Adding navigates to detail with refresh command visible

- **WHEN** the user confirms the add
- **THEN** the app navigates to the new series' detail route and a refresh command is visible as in-progress on that screen

#### Scenario: A prefilled term seeds the search on mount

- **WHEN** the Add Series screen is opened with a term prefilled (e.g. from the header quick-search fall-through)
- **THEN** the search input is seeded with that term and the debounced autosuggest runs for it on mount, so the local-miss → remote-add handoff lands the user in a live search
