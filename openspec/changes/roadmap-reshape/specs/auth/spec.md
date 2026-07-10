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
