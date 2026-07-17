# dep — delta for m10-deployment-posture

## MODIFIED Requirements

### Requirement: FRG-DEP-007 — health endpoint

The system SHALL expose an unauthenticated HTTP health endpoint reporting
liveness and readiness (DB reachable/integrity, scheduler running, migration
state), suitable for Docker HEALTHCHECK, returning non-2xx when unhealthy.
The unauthenticated response body SHALL be **minimal**: overall status, plus
— when unhealthy — the *names* of the failing components only. It SHALL
contain no filesystem path, migration revision, version string, task list,
or error text (FRG-SEC-008). The full per-component diagnostic detail
(component statuses, revisions, error strings) SHALL be available to
authenticated callers on the system surface, where the admin UI consumes
it.

- **Milestone**: M1; unauthenticated-body minimization M10.
- **Source**: sonarr-architecture.md §7.1 (Health resource, CheckHealth task); mylar-feature-surface .md §8 (BACKENDSTATUS-style flags — mylar-comicvine.md §1.3).
- **Notes**: Exempt from auth by design (recorded in STRIDE at M8). Rich per-provider health (CV/indexer status) is NFR observability; this endpoint is the container-level check. Detail moved behind auth in M10 (`m10-deployment-posture`).

#### Scenario: Healthy instance returns a minimal 200

- **WHEN** `GET /health` is requested on a running instance with the database reachable and the scheduler running
- **THEN** the response is 200 with a body reporting overall status only — no component detail, paths, revisions, or version strings

#### Scenario: Unhealthy component flips the endpoint non-2xx naming the component

- **WHEN** a monitored component is unhealthy (e.g., the database is unreachable or the scheduler is stopped)
- **THEN** `GET /health` returns a non-2xx status and the body identifies the failing component by name only — no error text, path, or revision detail

#### Scenario: No credentials required

- **WHEN** `GET /health` is requested with no authentication headers, cookies, or API key
- **THEN** the endpoint responds normally — it is reachable anonymously, making it usable as a Docker HEALTHCHECK probe

#### Scenario: Full diagnostics live behind authentication

- **WHEN** an authenticated caller requests the system health-detail surface
- **THEN** the per-component statuses previously exposed on `/health` (database, scheduler, migration state, with their diagnostic detail) are returned; the same request unauthenticated is rejected by the perimeter

## ADDED Requirements

### Requirement: FRG-DEP-017 — Documented deployment security posture

The repository SHALL contain a committed deployment-security posture
document (`docs/security/posture.md`) recording each decided position with
its rationale and review trigger, and the operator manual SHALL carry the
corresponding operator-facing guidance, kept in sync with it (FRG-PROC-011).
Positions the document SHALL cover, at minimum:

- TLS is terminated by the deployment layer (Tailscale or reverse proxy);
  in-app TLS is rejected;
- the three at-rest storage classes (encrypted provider credentials, hashed
  verify-only authentication data, plaintext library metadata), with
  full-database encryption rejected with rationale and full-disk encryption
  recommended to operators;
- the inbound DoS envelope as implemented (FRG-NFR-014 listener limits and
  WebSocket caps), including the recorded position on the archive-memory
  residual (RISK-005);
- the same-origin/no-CORS position (FRG-SEC-006);
- the trusted-proxy setting and its misconfiguration risk (FRG-SEC-007);
- a downgrade warning: rolling back below the first authenticated release
  (v0.9.0) reopens closed security gaps, stated in the manual's upgrade
  guidance;
- recommended container run flags (`no-new-privileges`, `cap_drop`,
  read-only rootfs guidance) in the manual's deployment section.

#### Scenario: Positions are citable

- **WHEN** an external reviewer (or the pentest scope statement) needs the project's stance on TLS, at-rest encryption, DoS bounds, CORS, or proxy trust
- **THEN** `docs/security/posture.md` states the position, its rationale, and its review trigger, without requiring reconstruction from code or scattered documents

#### Scenario: Manual carries the operator projection

- **WHEN** an operator follows the manual's deployment-security section
- **THEN** it provides the TLS deployment stories, the FDE recommendation, container run flags, trusted-proxy configuration with its warning, and the downgrade warning — consistent with the posture document

#### Scenario: Posture stays in sync

- **WHEN** a later change alters a decided position (e.g. revises proxy trust or adds a surface)
- **THEN** the same change updates the posture document and manual section, under the FRG-PROC-011 docs-sync obligation
