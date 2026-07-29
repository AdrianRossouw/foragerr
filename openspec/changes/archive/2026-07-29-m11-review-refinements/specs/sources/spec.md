# sources — delta for m11-review-refinements

## ADDED Requirements

### Requirement: FRG-SRC-014 — Group-key sibling proposal sweep on operator pick

The system SHALL, when an operator resolves a source review row to a
series — whether by matching an already-in-library series or by adding a
new one — sweep the acting entitlement's same-`group_key` siblings, scoped
to the acting entitlement's `source_id`, and rewrite each sibling's
proposal to that series. The sweep SHALL write **proposals only**: a swept sibling
keeps `review_status = "new"` and is never auto-committed, its proposed
match carries `auto = false`, and rows already `matched` or `ignored` are
never touched. The sweep SHALL run on the plain match path as well as the
add/degrade path, so picking the correct series for one row propagates the
convenience to its siblings regardless of whether that series was already
in the library. The system SHALL additionally expose a **bulk
apply-to-group** action that resolves an operator-picked series across an
explicit set of review entitlements in one request: an in-library pick
matches every member; a not-yet-added pick adds the series once and leaves
the remaining members as swept proposals for a single bulk accept.

- **Milestone**: M11 (m11-review-refinements).
- **Source**: rig dogfood 2026-07-28 (145-row groups; a search-pick on one
  row leaves siblings stale); extends the change-1 sibling sweep
  (FRG-SRC-008) whose recorded follow-up was source-scoping and whose
  original join key was the sibling's own proposed `cv_volume_id` rather
  than `group_key`.
- **Notes**: `group_key` is computed in Python (the read-path
  `stripped_key(query_term(human_name))`) scoped to one `source_id` — no
  stored column is introduced (a future option if scale demands the SQL
  pushdown the `cv_volume_id` sweep uses). Proposal-only semantics reuse
  the FRG-SRC-008 guard shape exactly; the sweep is a convenience, never a
  licence to accept unreviewed (FRG-IMP-023 review-first posture stands).

#### Scenario: A match-to-existing pick sweeps same-group siblings into proposals

- **WHEN** an operator matches one review row to an in-library series and
  other `new` rows in the same `group_key` and `source_id` exist
- **THEN** those siblings are rewritten to a proposal for that series
  (`auto = false`), their `review_status` stays `new`, and no sibling is
  committed — while rows already `matched` or `ignored` are untouched

#### Scenario: An add pick sweeps by group, not only by prior proposal

- **WHEN** an operator adds a new series for one review row and same-group
  siblings exist whose own prior proposals named a different volume or no
  plausible match
- **THEN** every `new` same-`group_key` sibling in that source is
  re-proposed to the added series, not only the ones that already proposed
  its volume

#### Scenario: Bulk apply-to-group resolves the whole group in one action

- **WHEN** an operator picks a series for a group of review entitlements
  via the bulk apply-to-group action
- **THEN** an in-library pick matches every listed member, a not-yet-added
  pick adds the series once and leaves the rest as swept proposals, and no
  member is committed except the ones the operator's action explicitly
  matches

#### Scenario: The sweep never crosses sources

- **WHEN** two sources contain review rows sharing the same `group_key`
- **THEN** a pick in one source rewrites only that source's siblings; the
  other source's rows are untouched
