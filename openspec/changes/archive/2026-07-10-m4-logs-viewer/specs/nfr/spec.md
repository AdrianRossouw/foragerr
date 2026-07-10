# nfr delta — m4-logs-viewer

## ADDED Requirements

### Requirement: FRG-NFR-015 — Bounded log capture with configurable retention

The in-app log buffer (FRG-API-021) SHALL be bounded by construction: its
capacity in records comes from configuration
(`log_buffer_records` / `FORAGERR_LOG_BUFFER_RECORDS`, default 2000),
validated at startup (a non-positive or non-integer value fails fast per
FRG-NFR-009), and the buffer SHALL never hold more than that many records —
the oldest record is evicted on overflow. Capture SHALL be O(1) per record
with no I/O in the logging hot path, and each buffered record SHALL store
only the already-formatted message so buffer memory is proportional to the
record cap.

- **Milestone**: M4 (m4-logs-viewer)
- **Source**: owner request 2026-07-10 (retention configuration).
- **Notes**: Retention here is capacity, not duration — a deliberate
  simplification for a memory-only buffer. **Audit-trail position**: this is
  an operator observability surface, not an audit log. A durable
  access/audit-log requirement (attribution, tamper evidence, retention
  policy) is deferred to the auth milestone — before authentication there
  are no distinct principals to attribute actions to. Recorded so the
  regulated-development trail shows the deferral was deliberate.

#### Scenario: Buffer never exceeds its configured bound

- **WHEN** more records than `log_buffer_records` are emitted
- **THEN** the buffer holds exactly the configured number of newest records and the oldest have been evicted

#### Scenario: Invalid retention setting fails fast

- **WHEN** the process starts with `FORAGERR_LOG_BUFFER_RECORDS=0` or a non-numeric value
- **THEN** startup fails with an actionable configuration error naming the setting
