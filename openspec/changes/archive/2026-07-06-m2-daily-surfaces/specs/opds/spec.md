# opds — delta for m2-daily-surfaces

## MODIFIED Requirements

### Requirement: FRG-OPDS-013 — Recent Additions shelf

The catalog SHALL provide a Recent Additions acquisition feed of the most recently imported issues, ordered newest first by file import time, paginated per the pagination requirement, and advertised on the root navigation feed.

- **Milestone**: M2
- **Source**: mylar-opds.md §1 (`_Recent` shelf), §6 baseline.
- **Notes**: The highest-value shelf for the actual use case (pick up this week's haul on the iPad). Ordering key is the issue file's `added_at` (import time), never release date. Uses the shared page-size settings (FRG-OPDS-006); no separate window config — pagination bounds the feed.

#### Scenario: Newest import tops the feed

- **WHEN** a new issue file is imported
- **THEN** it appears first in `/opds/recent` (ordering by import time, not release date), the root feed lists the Recent shelf, and page-size clamping applies as on every feed

#### Scenario: Entries are complete acquisition entries

- **WHEN** the Recent feed renders
- **THEN** each entry carries the same acquisition link, comic MIME type, and metadata as the series shelf's entries — a reader can download directly from Recent

### Requirement: FRG-OPDS-007 — Working OpenSearch (or none)

The catalog SHALL either (a) advertise an OpenSearch description link, serve a valid `application/opensearchdescription+xml` document, and implement the referenced search feed returning matching series/issues, or (b) advertise no search link at all; an advertised-but-unimplemented search is prohibited. M2 implements option (a): the root feed advertises the search link, the descriptor's URL template resolves to a search feed over series titles, and the search input is treated as hostile (bound parameters only, output through the escaping feed builder).

- **Milestone**: M2
- **Source**: mylar-opds.md §4/§5 W1 (search advertised but not implemented, no descriptor), §6.
- **Notes**: M1 shipped compliant option (b). The search feed keeps the OPDS posture: unauthenticated listener, id-only resolution for anything actionable, no raw-SQL interpolation, adversarial cases in the OPDS security tests.

#### Scenario: Descriptor and templated search round-trip

- **WHEN** a reader follows the root feed's `rel="search"` link and substitutes a query into the descriptor's template
- **THEN** the descriptor is valid `application/opensearchdescription+xml` and the search feed returns matching series as valid OPDS entries (navigation into each series' acquisition feed), empty-but-valid for no matches

#### Scenario: Hostile query terms are inert

- **WHEN** the search term contains SQL metacharacters, XML markup, or an oversized payload
- **THEN** the query executes as a bound parameter (no injection), output is escaped by the feed builder, oversized input is bounded, and the response is a normal (possibly empty) feed — never a 500 or reflected markup
