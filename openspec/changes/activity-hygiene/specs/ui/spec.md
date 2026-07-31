# ui — delta for activity-hygiene

## MODIFIED Requirements

### Requirement: FRG-UI-006 — Activity: queue screen

The UI SHALL provide a queue screen rendering the tracked-download queue live
(WS-driven): title, series/issue, progress (size/sizeleft), state,
warning/error status with expandable status messages, estimated completion,
and per-item remove (with delete-data and blocklist options). The table SHALL
stay inside its frame — wide content scrolls within the table's own
container, release-name tokens wrap, and the actions column is always
reachable; the page never scrolls sideways. A failed row SHALL NOT render a
progress bar or byte counts (its status chip and reason carry the
information). The screen SHALL page (the shared paging controls) rather than
cap at one page, and SHALL offer row selection with select-all (scoped to the
displayed page), a bulk
Remove using the same delete-data/blocklist options, and a one-click
**Clear failed** that removes every failed row in the queue in one
request regardless of paging — not merely those on the displayed page,
and offered whenever the queue holds a failed row even if the current
page shows none — after the same confirmation dialog. Bulk outcomes report per-row: rows that could not be removed stay
listed with their reasons.

- **Milestone**: M1; contained layout, honest failed rows, paging and
  bulk cleanup added in activity-hygiene.
- **Source**: sonarr-architecture.md §7.4 (Activity/Queue), §4.4-4.5 tracked download states; API queue requirement.
- **Notes**: "Queue tracking" leg of the slice. ImportBlocked resolution routes to the manual-import overlay (M2) — in M1 it may only display the blocked reason.

#### Scenario: Queue table renders from the queue endpoint

- **WHEN** the queue screen mounts against `/api/v1/queue`
- **THEN** each row renders title, series/issue, a status chip, progress, and size/remaining derived from the response

#### Scenario: WS progress advances rows without reload

- **WHEN** a WS progress message arrives for a queued item
- **THEN** that row's progress updates in place with no new `/api/v1/queue` fetch, and an item that reaches import leaves the table

#### Scenario: Import-blocked chip exposes reason popover

- **WHEN** a row has status `import_pending` or `import_blocked`
- **THEN** its status chip renders the blocked/pending variant and activating it reveals a popover containing the reason text

#### Scenario: Remove dialog offers blocklist option

- **WHEN** the user clicks remove on a queue item
- **THEN** a dialog appears with delete-data and blocklist options, and confirming issues the corresponding remove request


#### Scenario: The table never forces sideways page scroll

- **WHEN** the queue holds rows whose release names are long unbroken
  tokens, on a wide viewport
- **THEN** the table scrolls (if at all) within its own container, every
  row's actions remain visible and clickable, and the page body does not
  scroll horizontally

#### Scenario: Failed rows read by status, not by progress noise

- **WHEN** a row's status is failed
- **THEN** no progress bar or "0 B" byte counts render for it, and its
  series/issue columns still identify it even when the release name is an
  opaque token

#### Scenario: Clear failed empties the failure backlog in one action

- **WHEN** the operator clicks Clear failed with several failed rows
  present and confirms the dialog (choosing blocklist or not)
- **THEN** every failed row is removed with the chosen options in one
  request, rows that could not be removed stay listed with per-row
  reasons, and non-failed rows are untouched

#### Scenario: Bulk remove mirrors the single remove's semantics

- **WHEN** the operator selects several rows (select-all included) and
  removes them with delete-data and/or blocklist chosen
- **THEN** each row is removed under the same rules as the single remove
  — an importing row is refused per-row, blocklist writes use the same
  key, client removal is best-effort — and the outcome reports
  applied/errors per row
