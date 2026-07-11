# Delta: ui — m5-creator-suggestions

## MODIFIED Requirements

### Requirement: FRG-UI-028 — Creator profile screen

The UI SHALL provide a creator profile at `/creators/{id}` rendered to the
design handoff (§8): a gradient header carrying the large initials avatar,
the creator's name, roles line, publishers line, and a Follow/Following
button; three stat columns (Series · Issues in library as owned-of-total ·
Publishers) from the profile aggregates (FRG-API-023); and an "In your
library" section of work cards — cover (local endpoint), series title,
volume label where applicable, this creator's role chips for that series,
a meta line, and an owned/total progress bar — each card navigating to the
series detail. The profile SHALL additionally render the
**"More from <name>"** section (handoff §8): the creator's cached external
bibliography (FRG-API-024) as work cards — title, publisher/year meta line,
role chip where known — each carrying an **Add to library** button that
routes into the standard user-driven add flow prefilled for that volume;
the system SHALL never add a series from this section by itself. While the
first fetch is pending the section SHALL show an unobtrusive
gathering state; a creator whose fetched bibliography is empty (or entirely
in-library) SHALL render no section rather than an empty shell. An unknown
creator id SHALL render the standard not-found state.

- **Milestone**: M5
- **Source**: design handoff §8 (creator profile region incl. "More
  from"); FRG-API-023 profile aggregates; FRG-API-024 bibliography
  (m5-creator-suggestions).
- **Notes**: Role chips reuse the normalized-role vocabulary; progress
  bars reuse the house progress styling (series detail's owned/total).
  Back navigation returns to the grid preserving its filter state.

#### Scenario: Profile header and stats match the API

- **WHEN** the profile loads for a creator credited in two library series
- **THEN** the header shows avatar/name/roles/publishers and a working
  Follow button, and the three stat columns equal the API's seriesCount,
  ownedIssues-of-totalIssues, and publisherCount

#### Scenario: Library work cards render and navigate

- **WHEN** the "In your library" section renders
- **THEN** each card shows the local cover, title, this creator's role
  chips, and the whole-series owned/total progress bar, and clicking it
  navigates to that series' detail screen

#### Scenario: Unknown creator is a not-found state

- **WHEN** `/creators/{id}` is opened for an id the API 404s
- **THEN** the screen renders the standard not-found state rather than an
  error boundary or blank page

#### Scenario: More-from cards render from the cache with add hand-offs

- **WHEN** the profile renders for a creator with a fresh cached
  bibliography containing volumes not in the library
- **THEN** the "More from" section lists their cards (title,
  publisher/year), each Add button routes into the standard add flow
  prefilled for that volume, and no series is created without the user
  completing that flow

#### Scenario: Pending and empty bibliography states

- **WHEN** the profile renders while the first bibliography fetch is
  pending, and separately for a creator whose fetched bibliography is
  empty
- **THEN** the pending profile shows the gathering state in place of the
  section, and the empty case renders no section at all
