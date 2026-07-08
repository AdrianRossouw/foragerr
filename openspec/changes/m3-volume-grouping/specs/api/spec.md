# api Spec Delta

## ADDED Requirements

### Requirement: FRG-API-020 — Series grouping projection

The API SHALL expose a read projection of franchise groups for the grouped library
view: `GET /api/v1/series/groups` returning each franchise group with its member
series and an **aggregated** roll-up (member/series count, total and owned issue
counts) computed in a bounded way that does NOT multiply the existing per-series
statistics N+1 (a single aggregate query, not per-series stats per group). The
response SHALL use the standard paging envelope and conventions (FRG-API-006/002),
expose no secret, and be read-only. The existing flat `GET /api/v1/series` list SHALL
be unchanged except that each `SeriesResource` gains its `series_group_id` (nullable),
so a client can render a group affordance in the flat view without a second call.

#### Scenario: Grouped projection returns franchises with aggregated stats

- **WHEN** `GET /api/v1/series/groups` is called with three series across two franchises
- **THEN** it returns two groups, each listing its member series and an aggregated issue/owned roll-up, in the standard paging envelope, with no secret exposed

#### Scenario: Flat list carries the group id

- **WHEN** `GET /api/v1/series` is called
- **THEN** each series resource includes its `series_group_id` (or null), and the flat list's shape, sorting, and paging are otherwise unchanged

#### Scenario: Aggregation is bounded

- **WHEN** the grouping projection computes roll-up stats
- **THEN** it does so with a bounded aggregate query rather than the per-series statistics path multiplied per group (no N+1 explosion)
