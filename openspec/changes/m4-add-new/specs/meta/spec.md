# meta — delta for m4-add-new

## ADDED Requirements

### Requirement: FRG-META-015 — Relevance ordering of lookup candidates

The system SHALL order ComicVine lookup candidates by the plausibility signals
it already computes, server-side, before returning them: primary key name
similarity on the shared matching key (descending), tiebreak publication-year
proximity when the searched term carries a year, with the upstream ComicVine
order preserved as a stable final tiebreak. The same ordering SHALL apply
identically to the full lookup and the bounded suggest endpoint (FRG-API-017).
Ordering is presentation only: no candidate is dropped, no candidate is
auto-selected, and the annotated signals remain on every candidate so the user
can see why a result ranks where it does. (This deliberately supersedes the
original M1 stance that signals never influence order; the never-drop /
never-auto-pick half of that stance is unchanged, per FRG-META-007.)

#### Scenario: Closest title match ranks first

- **WHEN** a search term closely matches one candidate's matching key and only
  loosely matches others
- **THEN** the closest match is returned first, ahead of alphabetically-earlier
  but less similar candidates

#### Scenario: Ordering drops nothing and picks nothing

- **WHEN** a lookup returns candidates including ones with very low similarity
- **THEN** every candidate the search produced is still present (count
  unchanged, ignored-publisher exclusion aside) and none is marked selected

#### Scenario: Lookup and suggest agree on order

- **WHEN** the same term is sent to the full lookup and the suggest endpoint
- **THEN** the candidates they share appear in the same relative order

## MODIFIED Requirements

### Requirement: FRG-META-007 — Series search

The system SHALL provide a ComicVine series search by name (volumes endpoint with per-word name filters) that paginates to a bounded result count and annotates each candidate with plausibility signals — publication-year range, issue-count sanity for a target issue when given, already-in-library flag — and SHALL exclude publishers on a configurable ignore list.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.6 (findComic heuristics), §5; mylar-feature-surface.md capability map META (ignored-publishers).
- **Notes**: Keep Mylar's plausibility *annotations* but let the user (and the add flow) make the final choice — signals annotate and, since m4-add-new, order candidates (FRG-META-015); they never hard-drop except the publisher ignore list and never auto-pick. Result cap ~1000 with a visible truncation warning.

#### Scenario: Candidates annotated with plausibility signals, no auto-pick

- **WHEN** a known title is searched
- **THEN** each returned candidate carries plausibility annotations — similarity on the shared matching key, publication-year proximity, issue-count sanity for a target issue when supplied, and an already-in-library (`haveit`) flag for a series already present — and the search returns the annotated candidate list ordered per FRG-META-015 without auto-selecting one.

#### Scenario: Ignored-publisher volumes excluded

- **WHEN** the results include a volume whose publisher is on the configurable ignore list
- **THEN** that volume is absent from the returned candidates while other plausibility signals only annotate and order (do not hard-drop) the remaining candidates.

#### Scenario: Bounded result count with truncation warning

- **WHEN** a search would exceed the bounded result cap
- **THEN** the results are truncated to the cap and a visible truncation warning accompanies them.
