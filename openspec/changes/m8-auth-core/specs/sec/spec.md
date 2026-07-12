# sec Spec Delta

## MODIFIED Requirements

### Requirement: FRG-SEC-005 — CSRF stance and WebSocket Origin validation

All state-changing HTTP endpoints SHALL be protected against cross-site request forgery: programmatic access authenticates via the `X-Api-Key` header only (CSRF-immune by construction — the header must be attached deliberately), and the cookie-session UI surface SHALL combine SameSite=Lax session cookies with an Origin/Referer check that rejects unsafe-method (non-GET/HEAD/OPTIONS) requests whose Origin is foreign or absent under cookie authentication. The WebSocket handshake SHALL validate the request Origin against an allowlist (the deployment's own origin by default, configurable for reverse-proxy setups), refusing cross-origin socket connections before upgrade.

- **Milestone**: M8
- **Source**: STRIDE analysis (WebSocket auth required by FRG-AUTH uniform surface coverage, but Origin/CSWSH and API CSRF stance unaddressed). Gap G-5; RISK-022. Elaborated by m8-auth-core (2026-07-12) from the m8-auth pre-design: SameSite+Origin-check stance for the same-origin SPA, no token dance.
- **Notes**: Lands with the AUTH milestone core, closing G-5/RISK-022. This prevents a browser-resident attacker abusing the operator's ambient session now that sessions exist. No anti-CSRF token is needed for a same-origin SPA under SameSite=Lax plus the Origin check; revisit only if a cross-origin deployment mode ever appears.

#### Scenario: Forged cross-site state change is rejected

- **WHEN** a state-changing request arrives carrying a valid session cookie but a foreign Origin (or an absent Origin on an unsafe method not attributable to the SPA), as from a hostile page driving the operator's browser
- **THEN** the request is rejected before any state change with no side effect, while the same request from the deployment's own origin succeeds

#### Scenario: API-key surface is CSRF-immune by construction

- **WHEN** a cross-site attacker attempts to drive a state-changing API call from a victim browser without the API key
- **THEN** the call fails authentication — ambient cookies do not authenticate `X-Api-Key`-surface requests, and the key cannot be attached cross-site by a browser form or script without already possessing it

#### Scenario: Cross-origin WebSocket is refused pre-upgrade

- **WHEN** a WebSocket handshake arrives with an Origin outside the allowlist (default: the deployment's own origin), or with valid auth but a disallowed Origin
- **THEN** the handshake is refused before protocol upgrade and no socket is established, while a handshake from an allowed origin with valid credentials succeeds

#### Scenario: Reverse-proxy origins are configurable

- **WHEN** the operator configures an additional allowed origin for a reverse-proxied deployment and a WebSocket handshake arrives from that origin
- **THEN** the handshake passes Origin validation (auth still required), and origins not on the configured list remain refused
