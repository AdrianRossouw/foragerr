# m4-logs-viewer — System → Logs screen (M4, owner-requested)

## Why

During the m4-library-views demo review the owner could not diagnose why
nothing was downloading ("I wanted to see why Fables and Saga weren't
downloading even though I enabled GetComics") — the answer (the seeded
indexer defaults to interactive-only search) was only visible via the API or
container stdout. The operator needs an in-app way to see what the acquirer
and the rest of the backend are doing, *arr-style: System → Logs. The owner
also asked for a configurable retention bound. Requested 2026-07-10.

## What Changes

- **ADDED FRG-API-021 — Log records resource**: the backend keeps recent log
  records in a bounded in-memory ring buffer (a logging handler attached at
  startup, after the existing redaction filter so registered secrets never
  enter the buffer) and serves them from `GET /api/v1/log` — paged,
  newest-first, filterable by minimum level and logger prefix. Memory-only:
  a restart clears the buffer (container stdout remains the durable log).
- **ADDED FRG-UI-024 — System → Logs screen**: a Logs entry in the sidebar's
  SYSTEM group; a dense table (time, level pill, logger, message) with
  level/logger filters and a **follow** toggle that keeps the view at the
  newest records by polling the resource (deliberately no WS log push — a
  log→push→log feedback loop is designed out; decision 2). Follow-off allows
  paging back through the buffer.
- **ADDED FRG-NFR-015 — Bounded log capture with configurable retention**:
  the ring buffer's capacity is a config/env setting
  (`FORAGERR_LOG_BUFFER_RECORDS`, default 2000, validated at startup);
  capture cost is O(1) per record and the buffer can never grow past its
  bound. The requirement's Notes record the audit-trail position: this is an
  operator observability surface, not an audit log — a durable
  access/audit-log requirement is deliberately deferred to the auth
  milestone, when there are distinct principals to audit.
- New registry IDs allocated at proposal time: FRG-API-021, FRG-UI-024,
  FRG-NFR-015.
- **Process: tiered review gates codified** (owner decision 2026-07-10,
  during this change's proposal): `docs/process/commit-standard.md` item 6
  now scales the review fleet to diff size and risk class. This change is
  the first exercise: size-small BUT security-touching (a new endpoint
  serving log content), so its gate = small fleet + a dedicated adversarial
  secret-leak angle + Codex, and FRG-API-021 carries a tested
  no-secret-exposure scenario (owner requirement).

## Non-goals

- No durable log persistence, rotation, or shipping (stdout + container
  tooling remain the durable path); no access/audit log (deferred to M8 —
  recorded in FRG-NFR-015 Notes).
- No WS push for log records (polling only, decision 2).
- No log-level runtime mutation (FORAGERR_LOG_LEVEL stays the control).
- No download-pipeline behavior changes — this change only makes existing
  behavior visible.

## Capabilities

### New Capabilities

- none (all three requirements slot into existing capabilities).

### Modified Capabilities

- `api`: ADDED FRG-API-021 (log records resource).
- `ui`: ADDED FRG-UI-024 (System → Logs screen; FRG-UI-023's nav gains the
  Logs entry under SYSTEM — shipped-screens rule satisfied in the same
  change).
- `nfr`: ADDED FRG-NFR-015 (bounded capture + retention setting).

## Impact

Backend: a `logging` ring-buffer handler module + startup wiring, `GET
/api/v1/log` route, one setting (`log_buffer_records`) with validation;
pytest per requirement. Frontend: `screens/system/LogsScreen` + route + nav
entry (badge-less), React Query polling hook; vitest per scenario. Docs:
`docs/manual/user/web-ui.md` System section + a troubleshooting note in the
admin manual (manual impact declared: those two sections);
`docs/security/` STRIDE + risk register row for the new read endpoint
(information disclosure — mitigated by the pre-buffer redaction filter and
the Tailscale-only posture, RISK-020 lineage). SOUP: none (stdlib +
existing deps only). e2e: one spine scenario asserting the screen lists a
known record; SELECTORS.md entry if a testid is needed.

## Approval

Covered by the owner's 2026-07-10 standing grant (M4–M7) and his explicit
2026-07-10 request for log visibility; recorded per FRG-PROC-009.
