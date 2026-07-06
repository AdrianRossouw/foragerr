# meta — delta for m2-first-run-defaults

## MODIFIED Requirements

### Requirement: FRG-META-002 — API key handling

The system SHALL read the ComicVine API key from environment/`.env` configuration,
from the config file, OR from the settings UI (persisted to the config file), and
SHALL transmit it as a request parameter that is scrubbed from all log output, and
SHALL never write the key to logs, error messages, diagnostics, or persisted files
in plaintext beyond the config file/database at-rest surface already accepted. A
key set or changed through the settings UI SHALL take effect on subsequent
ComicVine requests WITHOUT a restart, because the key is resolved from the current
effective configuration per request; and the environment variable SHALL continue
to take precedence over a config-file/UI-supplied value, with that precedence
reported to the operator rather than silently overriding an edit.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.2, §4 (key-in-URL leak), §5; CLAUDE.md Secrets;
  m2-first-run-defaults (the key becomes UI-settable and live-applied).
- **Notes**: Requests will still carry `api_key` as a query parameter (ComicVine
  requires it); the requirement is that foragerr's own logging/telemetry redacts
  it. Security-relevant: update STRIDE/risk register in the same change
  (FRG-PROC-006). m2-first-run-defaults: the key may now be supplied via the
  settings UI (FRG-API-018) which persists it into `config.yaml` via the documented
  writer; because the ComicVine client is constructed per request from
  `app.state.settings` and reads the key fresh, swapping the settings object after a
  UI write applies the new key without a restart. Env precedence is unchanged
  (`FORAGERR_COMICVINE_API_KEY` still wins) and is surfaced by the settings resource
  as `source="environment"`. At-rest encryption of the persisted key remains M5
  (FRG-AUTH-008).

#### Scenario: Key is a SecretStr auto-registered with the redaction filter

- **WHEN** the ComicVine API key setting is loaded
- **THEN** it is held as a `SecretStr` and its value is auto-registered with the log
  redaction filter, so no configuration dump, diagnostic, or persisted file contains
  the plaintext key.

#### Scenario: Full add-series flow at debug level never emits the key

- **WHEN** a complete add-series flow (search, volume fetch, issue pagination, cover
  fetch) runs at debug log level with logs captured
- **THEN** no captured line contains any substring of the configured key, even
  though each request carried `api_key` as a query parameter.

#### Scenario: Key is masked inside exception tracebacks

- **WHEN** a request whose URL/params include the `api_key` parameter raises and its
  traceback is logged
- **THEN** the factory masks the api_key-shaped parameter and the emitted traceback
  shows a redaction placeholder in place of the key value.

#### Scenario: A UI-supplied key takes effect without a restart

- **WHEN** the ComicVine API key is set or changed through the settings UI (and no
  `FORAGERR_COMICVINE_API_KEY` environment variable is set)
- **THEN** subsequent ComicVine requests use the new key without restarting the
  application, because the key is resolved per request from the current effective
  configuration

#### Scenario: Environment precedence is preserved and reported

- **WHEN** `FORAGERR_COMICVINE_API_KEY` is set in the environment
- **THEN** the environment value remains the effective ComicVine key regardless of a
  config-file/UI-supplied value, and that precedence is reported to the operator
  (source is environment-managed) rather than a UI edit silently taking effect
