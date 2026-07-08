# ser Spec Delta

## ADDED Requirements

### Requirement: FRG-SER-016 — Volume grouping model and franchise derivation

The system SHALL support grouping series into **franchise groups** as an additive
display layer over the one-series-per-ComicVine-volume model (FRG-SER-001), without
altering series identity, matching, monitoring, or wanted state. A series' group SHALL
be **auto-derived** from a normalized **franchise key** computed from its title: the
existing series-name normalization (`parser.normalize.matching_key`) with trailing
volume-year and `Vol N` designators removed, so successive runs of one title
("Batman (2011)", "Batman (2016)") fold to the same key and share a group. Grouping
SHALL be applied at add and at refresh (find-or-create the group for the derived key
and link the series); a series whose key is empty or that the operator has not grouped
SHALL remain ungrouped (rendered as its own franchise of one). A group SHALL carry a
display title and its normalized key; groups SHALL have no files, monitor flag, or
wanted state.

#### Scenario: Successive runs of a title share a franchise group

- **WHEN** two series "Batman (2011)" and "Batman (2016)" exist
- **THEN** both derive the same franchise key, are linked to one "Batman" group, and the flat series view and their identity/wanted state are unchanged

#### Scenario: Grouping never alters wanted or monitoring

- **WHEN** a series is grouped
- **THEN** its `wanted_issues`/`series_statistics` results are byte-identical to before grouping, and the group itself is not a monitored entity

#### Scenario: An unresolved series stays ungrouped

- **WHEN** a series' franchise key is empty (untitled/edge) or it has no confident group
- **THEN** it is left ungrouped and appears as a single-run franchise in the grouped view, never forced into an unrelated group

### Requirement: FRG-SER-017 — Grouping manual override survives refresh

The operator SHALL be able to correct the grouping heuristic — rename a group, or
reassign a series to a different group or detach it — and the correction SHALL persist
across subsequent `refresh-series` runs. A series the operator has reassigned SHALL be
**locked** so that auto-derivation never overwrites the operator's choice (mirroring
the `aliases` user-override precedent, FRG-SER-014 edit flow); a renamed group SHALL
keep its identity (and its members) across refreshes. Clearing the lock SHALL return
the series to auto-derivation on the next refresh.

#### Scenario: Reassigned series is not re-derived by refresh

- **WHEN** the operator reassigns a series to a different group and a later `refresh-series` runs
- **THEN** the series stays in the operator-chosen group (its lock prevents re-derivation), while unlocked series continue to auto-derive

#### Scenario: Group rename persists

- **WHEN** the operator renames a franchise group
- **THEN** the new title survives refresh and the group keeps its member series
