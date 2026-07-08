# ser Spec Delta

## ADDED Requirements

### Requirement: FRG-SER-018 — Series collected-edition (trade) typing

The system SHALL type a series by its collected-edition **book-type**: a nullable
`booktype` on the series drawn from the existing parser `Booktype` vocabulary
(`tpb` / `gn` / `hc` / `one_shot`; null = an ordinary single-issues run). The book-type
SHALL be **auto-derived** from the series title at add and at refresh using the existing
`BOOKTYPE_CUES` (the same cues the filename parser uses); a series whose title carries
no collected-edition cue is typed null. The operator SHALL be able to set the book-type
explicitly, in which case it is **locked** (`booktype_locked`) so a later
`refresh-series` does not re-derive over the operator's choice (mirroring the
grouping-override precedent, FRG-SER-017); clearing the lock returns it to
auto-derivation. Typing is additive display/naming metadata: it SHALL NOT change series
identity, monitoring, wanted state, or matching. Where naming templates use
`{Booktype}`, a typed series' book-type is available for naming.

#### Scenario: Collected-edition title is auto-typed

- **WHEN** a series titled with a collected-edition cue ("… TPB", "… (Graphic Novel)") is added or refreshed and the operator has not locked its book-type
- **THEN** its `booktype` is derived from the cue (tpb/gn/hc), while a single-issues run with no cue is typed null, and neither series' identity/monitoring/wanted state changes

#### Scenario: Operator book-type override survives refresh

- **WHEN** the operator sets a series' book-type explicitly and a later `refresh-series` runs
- **THEN** the operator's book-type persists (it is locked, not re-derived); clearing the lock re-derives on the next refresh

### Requirement: FRG-SER-019 — Trades never suppress single-issue wanted

A series' collected-edition typing, and ownership of collected-edition (trade) files,
SHALL NEVER remove, hide, or de-prioritise any single issue from wanted, missing, or
searchable state — singles and trades are independent acquisition tracks. No book-type
predicate SHALL be introduced into the derived-wanted computation (`wanted_issues`) or
the series statistics (`series_statistics`); a trade line's files, being on a separate
ComicVine volume → separate series, SHALL attach only to that trade line's issues and
never to a single-issue series' issues. This invariant SHALL be verified by dedicated
tests.

#### Scenario: Owning a full trade line leaves single issues wanted

- **WHEN** a single-issues series has missing monitored issues (so they are wanted) and a fully-owned collected-edition series of the same title also exists
- **THEN** every single issue that was wanted remains wanted/missing/searchable — the trade line's ownership and typing change nothing about the singles

#### Scenario: Typing a series does not alter wanted or statistics

- **WHEN** a series is typed as a collected edition (auto or manual)
- **THEN** `wanted_issues` and `series_statistics` output is identical to before typing (no book-type predicate reached either)

#### Scenario: Pull matching still works for a typed line

- **WHEN** the pull matcher processes entries for a collected-edition-typed series
- **THEN** its existing book-type match guard still resolves the line's entries correctly (typing does not break pull matching)
