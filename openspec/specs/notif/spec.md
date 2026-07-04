# NOTIF — Notifications Specification

## Purpose

Baseline requirements for notifications, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).

## Requirements

### Requirement: FRG-NOTIF-001 — Generic notifier provider abstraction

Notifications SHALL be implemented as provider rows (implementation name + typed settings serialized per the provider pattern) behind a single notifier interface, such that adding a new channel requires only a backend implementation class and no frontend or event-pipeline changes.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §2.1 ThingiProvider pattern + §7.2 schema endpoints; mylar-feature-surface.md §6 (ten hardcoded agents — the anti-pattern being replaced).
- **Notes**: Foundation requirement for the area. Depends on the API provider-schema requirement; the UI notifications screen is drafted under UI.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Two different channel implementations are configurable side by side via the generic schema-driven settings form; removing one leaves the other functioning.

### Requirement: FRG-NOTIF-002 — Event catalog with per-connection opt-in

Each configured notifier connection SHALL independently opt in to each notification event type, covering at least: on grab (release snatched), on import (download imported), on upgrade (existing file replaced), on download failure, on health issue, and on test; events not opted into SHALL NOT be delivered to that connection.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §6 (per-agent `_ONSNATCH` gates; on-snatch / on-PP-complete / on-metatag-error events); sonarr-architecture.md §5.3 (EpisodeImportedEvent → notifications), §4.6 (DownloadFailedEvent).
- **Notes**: Event set deliberately extends Mylar's three (adds upgrade, failure, health) following Sonarr's event model; "metatagging error" folds into a general failure/health event rather than a bespoke type — divergence noted.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A connection opted into only "on import" receives nothing on grab and one message on import; toggling the flag changes behavior without restart.

### Requirement: FRG-NOTIF-003 — Event payload content

Notification messages SHALL include, per event type, at least: series title, issue number/title, and for grab events the indexer, release title, and size; for import events the final format and an upgrade indicator; for failure events the failure reason — rendered per-channel within that channel's formatting limits.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §4.3 grab history data dict (indexer, size, url), §7.3 HistoryResource fields; mylar-feature-surface.md §6.
- **Notes**: Keeps payload requirements channel-agnostic; per-channel niceties (embeds, markdown) are implementation detail, except cover images (separate requirement, B).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A grab notification on any configured channel names the series, issue, and indexer; an import notification distinguishes new file vs upgrade.

### Requirement: FRG-NOTIF-004 — Test action per connection

Every notifier connection SHALL support a test action (via the provider test endpoint) that sends a real test message through the configured channel and returns structured success/failure including the transport error on failure.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §6 (per-agent test endpoints, webserve.py:8197-8311); sonarr-architecture.md §7.2 (`POST /<provider>/test`).
- **Notes**: Rides on the API provider test requirement; listed separately so the NOTIF area owns the per-channel delivery semantics.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Test against a valid Discord webhook delivers a visible message and reports success; test against a revoked webhook reports failure with the HTTP error, without crashing or queuing retries.

### Requirement: FRG-NOTIF-005 — Starter channel set

The initial release of notifications SHALL include working implementations for: generic webhook (JSON POST), Discord, Telegram, Pushover, and email (SMTP with TLS and authentication).

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §6 (Mylar's ten agents; Discord/Telegram/Pushover/Email are the overlap chosen) and §(b) NOTIF candidate ("at least one push channel (e.g. webhook/Discord/Telegram/email)").
- **Notes**: Generic webhook is the escape hatch that makes every other service reachable day one. Selection rationale: highest-usage modern channels + email as lowest-common-denominator.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Each of the five channels passes its test action against a live endpoint and delivers at least grab and import events end-to-end.

### Requirement: FRG-NOTIF-006 — Additional channels (deferred)

The notifier abstraction SHALL accommodate later addition of the remaining Mylar-parity channels — Prowl, Boxcar, Pushbullet, Slack, Mattermost, Gotify — and Apprise-style aggregation, each as an ordinary provider implementation with no core changes.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §6 (full ten-agent list).
- **Notes**: Consider implementing the whole B set via a single Apprise dependency instead of six bespoke clients — decision for the implementing proposal. Backlog placement is deliberate: webhook covers the gap.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Adding one deferred channel (e.g. Gotify) touches only a new implementation module + registration, demonstrated by diff scope in its implementing change.

### Requirement: FRG-NOTIF-007 — Delivery isolation and failure handling

Notification delivery SHALL be asynchronous and isolated from the pipeline that raised the event: a slow or failing channel SHALL NOT block or fail grabs, imports, or commands; delivery failures SHALL be logged and repeated failures surfaced as a health warning for that connection.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §6.1 (handlers isolated, fire-and-forget async handlers), §6.2 asyncio equivalent; mylar-feature-surface.md §6 (no such isolation stated — hardening divergence).
- **Notes**: The event-bus mechanics belong to the backbone area; this owns the NOTIF-specific guarantee and health surfacing.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With an unreachable webhook configured, an import completes normally in the usual time; the failure appears in logs and, after repeated failures, in `GET /health`.

### Requirement: FRG-NOTIF-008 — Cover image attachments

For channels that support image attachments/embeds (Discord, Telegram, Pushover), import notifications SHALL optionally attach the issue's cover image sourced from the local cover cache.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §6 (cover-image attachment for Pushover/Telegram/Discord/Mattermost/Gotify, extracted via getimage.py).
- **Notes**: Depends on the local cover cache (shared with the OPDS cover-fallback requirement) — reuse, do not re-extract from archives per notification.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With the option enabled, a Discord import notification carries the cover embed; with it disabled, text only.

