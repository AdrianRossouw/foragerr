# ui delta — m4-logs-viewer

## ADDED Requirements

### Requirement: FRG-UI-024 — System → Logs screen

The SPA SHALL provide a Logs screen under the sidebar's SYSTEM group
(`/system/logs`) rendering the FRG-API-021 resource as a dense table —
time, level pill (semantic colors: ERROR danger, WARNING warn, INFO
neutral, DEBUG muted), logger, message — with a minimum-level filter, a
logger-prefix filter, and a **Follow** toggle. With Follow on, the screen
SHALL poll the resource on a short interval (≥ 2s) and keep the newest
records in view; with Follow off, polling SHALL stop and the operator can
page back through the buffer. Polling SHALL also stop when the screen
unmounts. The screen SHALL render an honest empty state when the buffer is
empty and an error state when the resource fails (never a silent blank
per the UAT negative-path rule).

- **Milestone**: M4 (m4-logs-viewer)
- **Source**: owner request 2026-07-10; Sonarr System→Log prior art.
- **Notes**: Nav entry ships with this screen (FRG-UI-023 shipped-screens
  rule). No WS log family — polling only (design decision 2).

#### Scenario: Logs table renders with filters

- **WHEN** the operator opens System → Logs with mixed-level records buffered and applies a minimum level and a logger prefix
- **THEN** the table shows only matching records (time, level pill, logger, message), newest first

#### Scenario: Follow polls and stops

- **WHEN** Follow is on
- **THEN** the resource is re-fetched on the polling interval and new records appear without a reload; turning Follow off (or leaving the screen) stops the polling

#### Scenario: Empty and error states are honest

- **WHEN** the buffer is empty, or the log resource request fails
- **THEN** the screen states that no records are buffered (or that loading failed) rather than rendering a silent blank table
