# ui — delta for m2-lookup-error-surfacing

## MODIFIED Requirements

### Requirement: FRG-UI-005 — Add-series search screen

The UI SHALL provide an add-series screen where the user searches ComicVine by title (or pastes a ComicVine volume id/URL), sees candidate volumes with poster, year, publisher, and issue count, and adds one with root folder, monitoring strategy, and format-profile selections. The screen SHALL distinguish the non-success search outcomes — a lookup error (including ComicVine credential failure, classified by the API's machine-readable field discriminator and rendered with guidance to check Settings), an incomplete result (degraded walk), a capped result (advising a narrower search), and a genuinely empty result — never rendering an error, degraded, or capped outcome as plain "no results", rendering exactly one outcome state at a time, and always honouring a re-submitted search (a same-term retry issues a fresh lookup rather than serving the failed or degraded result from cache).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (AddSeries lookup), §1.2 add flow; mylar-feature-surface.md §SER (add by CV search or CV ID).
- **Notes**: First leg of the vertical slice. "Import existing library" mass-add flow is a separate M2 requirement below — keep them distinct. Outcome-state distinction added in m2-lookup-error-surfacing: a missing/invalid ComicVine key previously rendered as "no results".

#### Scenario: Search renders CV candidates with plausibility annotations

- **WHEN** the user types a title and the ComicVine lookup returns candidates
- **THEN** each candidate renders poster, year, publisher, and issue count, and any plausibility annotations returned are rendered on the candidate

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
- **THEN** the add panel renders controls for root folder, format profile, monitor strategy, and search-on-add

#### Scenario: Adding navigates to detail with refresh command visible

- **WHEN** the user confirms the add
- **THEN** the app navigates to the new series' detail route and a refresh command is visible as in-progress on that screen
