## MODIFIED Requirements

### Requirement: FRG-AUTH-001 — M1/M2 no-auth accepted risk

Until AUTH ships (M3), the system SHALL operate without authentication on the web UI, API, and OPDS surfaces, with this documented as an accepted risk in the risk register whose compensating control is Tailscale-only network exposure (see DEP).

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 AUTH (auth modes incl. none); CLAUDE.md (Tailscale, FRG-PROC-006 security-is-spec'd).
- **Notes**: Deliberate: shipping "auth mode: none" as the only M1 mode. FRG-PROC-006 requires the STRIDE/risk-register update in the same change that adds any listener — this requirement makes the acceptance explicit rather than implicit.

#### Scenario: All surfaces respond without credentials in auth mode "none"

- **WHEN** the M1 application is running and requests are made to `/health` and to `/api/v1/*` routes with no credentials, session, or API key of any kind
- **THEN** the requests succeed (2xx per route semantics), and a route-inventory test asserts that no auth middleware or auth dependency is registered on the app or any route

#### Scenario: Accepted risk is recorded with its compensating control

- **WHEN** the risk register and deployment docs are inspected as part of the M1 change
- **THEN** `docs/security/risk-register.md` RISK-020 records the no-auth acceptance with owner approval, restated in this change with Tailscale-only exposure (FRG-DEP-011) cited as the compensating control (not a second independent acceptance), and deployment docs state the tailnet-only constraint

#### Scenario: No half-built auth code paths exist before M3

- **WHEN** the M1 codebase and OpenAPI document are inspected
- **THEN** no dormant login routes, password/credential fields, session machinery, or partially wired auth dependencies exist — auth mode "none" is the only mode present, with nothing latent for M3 to accidentally half-enable
