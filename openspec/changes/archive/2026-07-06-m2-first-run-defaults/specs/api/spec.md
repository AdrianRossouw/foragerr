# api — delta for m2-first-run-defaults

## ADDED Requirements

### Requirement: FRG-API-018 — ComicVine credential settings resource

The API SHALL expose a settings resource that lets the UI READ the ComicVine API
key's configured STATUS and SOURCE, UPDATE the key, and TEST ComicVine
connectivity — without the key value ever leaving the server in a response. The
read SHALL return whether the key is configured and its source — `unset`,
`file` (set in `config.yaml`), or `environment` (set via
`FORAGERR_COMICVINE_API_KEY`) — and SHALL NEVER return the key value. An update
SHALL persist a supplied key into `config.yaml` through the existing atomic
documented-config writer (so the key is written as a real value, not a commented
placeholder) and SHALL apply it to the running application WITHOUT a restart; a
blank update SHALL keep the currently-stored value rather than clearing it. Because
the `FORAGERR_COMICVINE_API_KEY` environment variable takes precedence over the
config file, when the key's source is `environment` the resource SHALL report it as
environment-managed and SHALL reject an update as ineffective (naming the
environment variable) rather than silently persisting a shadowed value. The
connectivity test SHALL exercise ComicVine with the effective key and report
success or failure. In no case SHALL the key value appear in any response body or
log line, and an updated key SHALL be registered with the log-redaction filter.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §4 (provider/connection settings with test);
  m2-first-run-defaults (the "check Settings" guidance needs a real settings-write
  surface); FRG-API-013 (the config-resource pattern this extends — read-modify-
  write-reload with `render_documented_config` + `atomic_write_text` under a write
  lock), FRG-META-002 (ComicVine key handling + redaction), FRG-IDX-003 (the
  provider connectivity-test contract this mirrors for ComicVine).
- **Notes**: FRG-API-013's existing `naming`/`mediamanagement` resources
  deliberately carry no secret fields, so this is a NEW resource, not a
  modification of them. Persistence reuses `render_documented_config`, which already
  writes a supplied secret uncommented — no separate secrets store is introduced.
  Live-apply is the existing `app.state.settings` swap: the ComicVine client is
  constructed per request and reads the key fresh, so the swap suffices with no
  client-recreation plumbing. Source detection reads
  `os.environ["FORAGERR_COMICVINE_API_KEY"]` directly — the one place that must
  distinguish env from file, because the effective `Settings` object collapses both
  sources. Security (FRG-PROC-006): a new state-changing endpoint that accepts a
  secret from the (tailnet-only, unauthenticated — RISK-020) UI and persists it in
  plaintext (RISK-013, at-rest encryption is M5/FRG-AUTH-008); mitigations are
  write-only-over-the-API (GET never returns the value) + log redaction on write —
  recorded as a `docs/security/` delta in this change.

#### Scenario: Read reports configured status and source, never the value

- **WHEN** the ComicVine credential settings resource is read
- **THEN** the response reports whether the key is configured and its source
  (`unset`, `file`, or `environment`) and does NOT contain the key value or any
  substring of it

#### Scenario: Update persists the key and applies it without a restart

- **WHEN** a non-blank ComicVine API key is submitted to the resource and no
  `FORAGERR_COMICVINE_API_KEY` environment variable is set
- **THEN** the key is written into `config.yaml` as a real value via the atomic
  documented-config writer, the running application uses the new key on the next
  ComicVine request without a restart, the response does not echo the key, and the
  new value is registered with the log-redaction filter

#### Scenario: A blank update keeps the stored key

- **WHEN** the resource receives an update with a blank ComicVine API key
- **THEN** the currently-stored key is retained (not cleared), matching the
  write-only "leave blank to keep" convention used by provider secret fields

#### Scenario: An environment-supplied key is reported read-only and not shadowed

- **WHEN** `FORAGERR_COMICVINE_API_KEY` is set and an update is submitted to the
  resource
- **THEN** the read reports `source="environment"`, and the update is rejected as
  environment-managed (naming the environment variable) rather than persisting a
  value the environment would shadow

#### Scenario: Connectivity test uses the effective key without leaking it

- **WHEN** the connectivity-test action is invoked
- **THEN** it exercises ComicVine with the effective key and returns a success or
  failure result, and neither the response nor any log line contains the key value

#### Scenario: The key value never appears in a response or log

- **WHEN** any of the resource's read, update, or test actions runs
- **THEN** no response body and no emitted log line contains the ComicVine API key
  value
