# imp — delta for import-atomicity

## ADDED Requirements

### Requirement: FRG-IMP-027 — Per-group import atomicity (no zombie series shell)

The system SHALL treat a Library Import group's series creation as
atomic with its file attachment: when importing a group creates a **new**
library series but the group does not go on to attach at least one file
(a metadata-refresh failure, a post-add error, or all files blocked), the
newly created series SHALL NOT persist — it, its monitored flags, and any
add-enqueued refresh/search side effects are rolled back or never
committed, so the library never silently retains a monitored, auto-grabbed
shell for a group the operator was told failed. A group that attaches at
least one file keeps its series; a series that already existed before the
group ran (a reuse / in-place re-run) SHALL NEVER be deleted by this rule
— only a shell THIS group created is undone. The group's staging row
SHALL still record the honest failure reason (unchanged), and a
subsequent scan/import of a rolled-back group SHALL behave as a first run,
never blocked as a duplicate by a leftover shell.

- **Milestone**: B (import-heuristics hardening, from the parked
  m11-import-intelligence-predesign item 7).
- **Source**: owner dogfood 2026-07-29 (an import "showed an error message
  but then somehow completed behind the scenes"); the parked pre-design's
  atomicity item.
- **Notes**: The failure was that `add_series` commits the series before
  the refresh/attach steps, and no path rolls it back — so the normal
  monitoring + scheduled-refresh + backlog-search machinery "completes" a
  group the operator saw fail. This requirement makes the group's series
  contingent on the attach actually happening. Per-group isolation
  (FRG-IMP-023) and the visible per-group reason are unchanged.

#### Scenario: A refresh failure after series creation leaves no series

- **WHEN** a Library Import group for a not-yet-in-library volume creates
  the series, then its pre-import metadata refresh fails
- **THEN** no series row remains for that volume, no monitored/wanted
  issues were created, no search was enqueued for it, and the group's
  staging row shows the refresh-failure reason

#### Scenario: A genuinely imported group keeps its series

- **WHEN** a group creates a series and attaches at least one file
- **THEN** the series persists exactly as today, with its imported files
  and the group marked imported

#### Scenario: A pre-existing series is never deleted by a failed group

- **WHEN** a group reuses (or re-runs in place against) a series that
  already existed before this group ran, and the group then fails to
  attach files
- **THEN** the pre-existing series is left intact — only a shell created
  by THIS group is rolled back

#### Scenario: A rolled-back group re-imports as a first run

- **WHEN** the operator re-runs the scan/import for a group whose series
  was rolled back
- **THEN** it proceeds as a first import (creating the series), never
  refused as a duplicate by a leftover shell
