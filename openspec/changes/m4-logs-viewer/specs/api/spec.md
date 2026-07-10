# api delta — m4-logs-viewer

## ADDED Requirements

### Requirement: FRG-API-021 — Log records resource

The backend SHALL capture log records emitted at or above the configured
log level into a bounded in-memory ring buffer (capacity per FRG-NFR-015)
via a `logging` handler attached at startup, and SHALL serve them from
`GET /api/v1/log` — paged, newest-first, filterable by minimum level
(`level`) and dotted logger-name prefix (`logger`). Each served record
carries timestamp, level, logger name, and the formatted message. The
buffer handler SHALL be attached downstream of the secret-redaction filter
so that a registered secret value can never enter the buffer; the resource
therefore SHALL never serve an unredacted registered secret. The buffer is
memory-only: a restart clears it (container stdout remains the durable
log), and the endpoint SHALL respond normally (an empty page) when the
buffer is empty.

- **Milestone**: M4 (m4-logs-viewer)
- **Source**: owner request 2026-07-10 (demo review — acquisition
  debugging); Sonarr System→Log prior art.
- **Notes**: Read-only observability surface, NOT an audit log (see
  FRG-NFR-015 Notes). No WS push family for logs — the UI polls
  (design decision 2: a log→push→error→log feedback loop is designed out).

#### Scenario: Paged newest-first read with filters

- **WHEN** records exist from several loggers and levels and the client requests a page with `level=WARNING` and a `logger` prefix
- **THEN** only records at WARNING or above whose logger name starts with the prefix are returned, newest first, with paging metadata consistent with the filtered total

#### Scenario: Registered secret never served

- **WHEN** a log record whose message contains a registered secret value (e.g. an API key) is emitted
- **THEN** the record served by `GET /api/v1/log` carries the redacted form and the raw secret value appears nowhere in the response body

#### Scenario: Empty buffer after restart

- **WHEN** the process restarts and `GET /api/v1/log` is called before new records accumulate
- **THEN** the endpoint returns an empty page (not an error), and subsequent records appear on later reads
