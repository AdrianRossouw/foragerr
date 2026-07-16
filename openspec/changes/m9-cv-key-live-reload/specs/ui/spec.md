# ui — m9-cv-key-live-reload deltas

## ADDED Requirements

### Requirement: FRG-UI-030 — Command failure cause surfaced at the watch surface

WHEN a watched command reaches the `failed` status, the web UI SHALL display the command's recorded failure reason alongside the failed status at the surface that watches it (e.g. the series page's command chip), rather than the bare status alone. The reason is the command record's verbatim `error` field (already captured per FRG-SCHED-008); when the record carries no reason, the bare status renders as before.

- **Milestone**: M9 (m9-cv-key-live-reload)
- **Source**: M9 simulated-user finding F1 — a failed first refresh rendered only "Refresh: failed"; the actionable cause (`comicvine authentication failed (HTTP 401)`) was already delivered to the client in the command resource and simply not shown.
- **Notes**: Display-only: `useWatchedCommand` exposes the resource's `error` when terminal-failed; no new API surface. Long reasons may be truncated visually but the full text stays available (e.g. `title`).

#### Scenario: Failed refresh shows its cause

- **WHEN** a series refresh command fails with a recorded error (e.g. a ComicVine authentication failure)
- **THEN** the series page's command status shows the failed status together with the recorded reason, not "failed" alone

#### Scenario: Reason-less failure degrades gracefully

- **WHEN** a watched command fails without a recorded error string
- **THEN** the status chip renders the failed status exactly as before this change
