## MODIFIED Requirements

### Requirement: FRG-DEP-001 — Docker image per linuxserver.io conventions

The system SHALL be packaged as a single Docker image following linuxserver.io conventions: PUID/PGID environment variables mapping the runtime user, a single `/config` volume for all persistent state, s6-overlay-style (or compatible) init, and TZ support.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 DEP (Dockerfile + init scripts); CLAUDE.md deployment target (linuxserver.io conventions — project-level source).
- **Notes**: Deployment IS M1: the vertical slice ships as this image running on the owner's home server over Tailscale. Media library mounts (e.g., `/comics`, `/downloads`) are additional volumes but hold no application state.

#### Scenario: Multi-stage build serves frontend, api, opds, and health

- **WHEN** the multi-stage Dockerfile is built (node stage builds the frontend, python-slim + uv stage installs the backend and copies the static frontend) and the container is run
- **THEN** FastAPI serves the static frontend at `/`, the API at `/api`, the catalog at `/opds`, and the health check at `/health`, with `EXPOSE 8789` and a `HEALTHCHECK` that probes `/health`

#### Scenario: PUID/PGID drop-privilege and TZ

- **WHEN** the container is started with `docker run -e PUID=1000 -e PGID=1000 -e TZ=... -v ./config:/config -p 8789:8789 foragerr`
- **THEN** the s6-overlay-compatible init drops privileges to 1000:1000, applies the timezone, the container reports healthy, and files created under `/config` are owned by 1000:1000

#### Scenario: Single /config volume preserves all state across restart

- **WHEN** the container is destroyed and recreated against the same `/config` volume
- **THEN** all application state (database, config, logs, caches under `/config`) is preserved and behavior is identical, with the container filesystem treated as disposable

#### Scenario: Build script secret-scans the build context

- **WHEN** the image build script runs
- **THEN** it performs a secret scan over the build context and fails the build if any secret material is present

### Requirement: FRG-DEP-011 — Tailscale-scoped exposure

The system SHALL bind its HTTP listener on a configurable address/port (default all interfaces inside the container) and SHALL be documented and operated as reachable only via the home server's Tailscale network in M1-M2, with no requirement to be internet-safe before AUTH (M3).

- **Milestone**: M1
- **Source**: CLAUDE.md (OPDS for iPad over Tailscale); mylar-feature-surface.md §8 AUTH (Mylar's interface host/port).
- **Notes**: This is the deployment-side statement of the accepted M1 no-auth risk (AUTH has the matching requirement). HTTPS/self-signed-cert generation from Mylar is NOT baselined — Tailscale provides transport security; revisit only if exposure model changes.

#### Scenario: Deployment docs state Tailscale-only exposure as the RISK-020 control

- **WHEN** the deployment documentation is reviewed
- **THEN** it states Tailscale-only reachability as the compensating control for the M1 no-auth posture (RISK-020), includes an explicit do-not-port-forward warning, and the risk register records "no auth before M3, network-scoped exposure"

#### Scenario: Compose example binds to the tailnet with no app TLS

- **WHEN** the provided compose example is inspected
- **THEN** it binds the listener to the tailnet address rather than a public interface, and the app performs no TLS termination (transport security is provided by the tailnet)
