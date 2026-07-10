# auth delta — roadmap-reshape

## MODIFIED Requirements

### Requirement: FRG-AUTH-008 — at-rest secret encryption

The system SHALL store replayable secrets it persists (outbound service keys entered via UI, OPDS/Basic credentials if reversibly needed, session signing material) encrypted with authenticated encryption under a key held outside the database (derived from an environment-supplied secret), not obfuscated. The encryption key SHALL be supplied via the environment only and SHALL never be stored in a file under `/config` or elsewhere in the deployment.

- **Milestone**: M6 (moved from M5 by roadmap-reshape, 2026-07-10 — the sources milestone stores store-account credentials, e.g. Humble Bundle, which require this control before they exist; application auth remains M8)
- **Source**: mylar-feature-surface.md §7 ("at-rest obfuscation of secrets ... salted-base64 ^~$z$ marker") — explicit better-than-Mylar divergence; mylar-ddl.md §4 (plaintext cookie storage); owner direction 2026-07-10 (env-only key; RISK-041 note).
- **Notes**: Primary secret path remains env vars (DEP) — this covers whatever the app itself persists. Key from env means the DB file alone (e.g., in a backup) does not expose secrets; document the recovery implication (losing the environment key means losing stored credentials). Existing provider keys migrate into the encrypted store when it lands (owner decision 2026-07-10) so there is one store, not two. Key-rotation edge cases (re-encryption path, restores across rotation, old-key grace) are explicitly deferred to the user-accounts milestone and MUST be designed there.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** DB and config-file inspection reveals no plaintext or base64-decodable secret values; tampering with ciphertext is detected (auth tag failure), not silently decoded.

#### Scenario: Key never persisted

- **WHEN** the deployment's `/config` volume and the application's files are inspected after normal operation including a backup cycle
- **THEN** the encryption key appears in no file — it exists only in the process environment, and a backup restored without the environment key cannot decrypt stored credentials

### Requirement: FRG-AUTH-001 — M1/M2 no-auth accepted risk

Until AUTH ships (M8, per the 2026-07-10 roadmap reshape), the system SHALL operate without authentication on the web UI, API, and OPDS surfaces, with this documented as an accepted risk in the risk register whose compensating control is Tailscale-only network exposure (see DEP).

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 AUTH (auth modes incl. none); CLAUDE.md (Tailscale, FRG-PROC-006 security-is-spec'd).
- **Notes**: Deliberate: shipping "auth mode: none" as the only M1 mode. FRG-PROC-006 requires the STRIDE/risk-register update in the same change that adds any listener — this requirement makes the acceptance explicit rather than implicit.

#### Scenario: All surfaces respond without credentials in auth mode "none"

- **WHEN** the M1 application is running and requests are made to `/health` and to `/api/v1/*` routes with no credentials, session, or API key of any kind
- **THEN** the requests succeed (2xx per route semantics), and a route-inventory test asserts that no auth middleware or auth dependency is registered on the app or any route

#### Scenario: Accepted risk is recorded with its compensating control

- **WHEN** the risk register and deployment docs are inspected as part of the M1 change
- **THEN** `docs/security/risk-register.md` RISK-020 records the no-auth acceptance with owner approval, restated in this change with Tailscale-only exposure (FRG-DEP-011) cited as the compensating control (not a second independent acceptance), and deployment docs state the tailnet-only constraint

#### Scenario: No half-built auth code paths exist before the auth milestone

- **WHEN** the M1 codebase and OpenAPI document are inspected
- **THEN** no dormant login routes, password/credential fields, session machinery, or partially wired auth dependencies exist — auth mode "none" is the only mode present, with nothing latent for the auth milestone to accidentally half-enable
