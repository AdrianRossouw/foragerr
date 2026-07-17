# m10-deployment-posture — design

Elaborates the m10-go-live pre-design (§1 Transport, §2 At-rest, §9
Hardening sweep) into this change's specifics. Where this document and the
pre-design disagree, this document wins.

## Context

Verified current state (2026-07-17): session cookies set
`secure=request.url.scheme == "https"` (`backend/src/foragerr/auth/routes.py:76,86`)
— silently never `Secure` behind a TLS proxy; no security response headers
anywhere; `/health` returns `db.health()` (includes the DB path), migration
`current`/`head` revisions, the scheduler task list, and `str(exc)` error
strings to unauthenticated callers; unhandled-500 hygiene is untested. The
DoS envelope already exists (FRG-NFR-014: streaming body cap, header cap,
per-client rate cap, time-to-first-byte timeout in `api/limits.py`; WS caps
in `foragerr.ws`) — this change documents it rather than rebuilding it.

## Goals / Non-Goals

**Goals:** fix the three verified gaps; make every delegated or rejected
control a written position the pentest scope statement can cite; leave no
aged residual undecided.

**Non-Goals:** in-app TLS; full-DB encryption; any auth-flow change; any
new listener limit (NFR-014 suffices); release-pipeline work.

## Decisions

### 1. Headers via one perimeter middleware, per-surface CSP values

A single response-header middleware wraps all mounted surfaces (same
install point as the limits middleware, HTTP scope only). Baseline on every
response: `X-Content-Type-Options: nosniff`,
`Referrer-Policy: same-origin`, `X-Frame-Options: DENY`. CSP differs by
surface: the SPA gets a real policy (`default-src 'self'`; `img-src 'self'
data:`; no external origins — the frontend is fully self-hosted, which this
change proves by test rather than assumes); API/OPDS/health responses get
the deny-everything `default-src 'none'; frame-ancestors 'none'` (their
bodies are data, not documents). `frame-ancestors` rides the CSP. Rationale
for per-surface: one blanket document-CSP on JSON/XML responses is inert
noise, while a too-loose SPA policy defeats the point. Alternative (CSP
only on the SPA) rejected: headers on data responses are free
defense-in-depth against content-type confusion.

### 2. Trusted proxy: explicit peer allowlist, one setting governs all

New config `server.trusted_proxies: list[str]` (default empty = today's
behavior exactly). When the **direct peer's** address is in the list, the
request's effective scheme comes from `X-Forwarded-Proto` and its effective
client IP from the rightmost non-trusted entry of `X-Forwarded-For`;
otherwise both headers are ignored (never "when present"). The effective
values feed the cookie `Secure` decision, the FRG-NFR-014 rate-limiter key,
and the `auth.*` audit `client_ip` — one setting, three consumers, no
skew. Implemented in the perimeter middleware stack so every consumer sees
the same resolved values on the request scope. Alternatives: uvicorn's
`--proxy-headers`/`ForwardedAllowIps` rejected — it exists, but resolving
in our own middleware keeps the decision visible, testable at the app
layer, and consistent in the e2e harness; a bare boolean `behind_proxy`
rejected — trusting any peer invites the spoofing misconfiguration the
risk register warns about.

### 3. Health: status + failing component names, detail behind auth

Unauthenticated `GET /health` returns `{"status": "ok"}` (200) or
`{"status": "down", "failing": ["database", ...]}` (503) — component
*names* only, preserving Docker HEALTHCHECK and "which subsystem" triage
without paths, revisions, task lists, or error strings. The current
detailed payload moves to the authenticated system surface
(`/api/v1/system/health/components`), where the admin UI can consume it.
Alternative (bare status only, no names) rejected: naming the failing
component discloses nothing actionable to an attacker (component names are
public in the source) and saves the operator a login during an outage.

### 4. Error hygiene: prove it, don't just configure it

FastAPI's default unhandled-exception path (debug off) already returns a
bare 500; this change adds an app-level handler that guarantees the
JSON error envelope with a generic message plus a structured log entry
with the traceback (server-side only), and a test that raises from a
route and asserts: 500, no traceback text, no exception class name, no
path disclosure in the body. A grep-test asserts no `debug=True` /
`FORAGERR_DEBUG` pathway exists in the packaged app factory.

### 5. Posture document lives in `docs/security/posture.md`

One document, position-per-section, each with its rationale and review
trigger: TLS delegation; at-rest classes + full-DB-encryption rejection +
FDE recommendation; DoS envelope (citing FRG-NFR-014 and the WS caps);
zipfile-OOM position (RISK-005 restated: bounded by NFR-014 body caps at
the listener and FRG-SEC-003 limits at the archive layer; residual
accepted); no-CORS position; downgrade warning (below v0.9.0 reopens
RISK-020's throttling gap). The pentest scope statement (final M10 change)
cites sections of this document by name. Manual gets the operator-facing
projection (how to deploy well), the posture doc keeps the why.

### 6. Aged residuals: recommend re-accept, decide at implementation

FRG-DEP-012 (diagnostic bundle): recommend formal re-accept to backlog with
a "revisit at first real support case" trigger — 1.0 does not need a
support-bundle feature, and building one now adds surface during a
hardening change. RISK-008 (DDL extractor): re-affirm with current
FRG-SEC-003 controls cited. Both decisions recorded in the risk register /
registry notes during implementation; if the owner prefers implementing
DEP-012 instead, it becomes its own small change, not a rider here.

## Risks / Trade-offs

- [CSP breaks the SPA (inline styles/scripts from the bundler)] → e2e suite
  runs against the headered app; the accessibility/e2e gate (FRG-PROC-019
  harness) catches violations; policy is tuned to the actual bundle output,
  loosened only with a recorded rationale (e.g. `style-src 'unsafe-inline'`
  if the UI library requires it — documented if so).
- [Trusted-proxy misconfiguration (wrong address trusted)] → risk-register
  row; manual wording "only the address of a proxy you run"; default-empty
  setting; e2e negative test proving forwarded headers from an untrusted
  peer are ignored.
- [Operators scraping /health detail break] → CHANGELOG upgrade note; the
  detail exists authenticated; health *semantics* (200/503) unchanged, so
  Docker HEALTHCHECK and uptime monitors keep working.
- [Header middleware ordering surprises (headers missing on error paths)] →
  middleware installed outermost so 4xx/5xx and exception responses carry
  headers too; test asserts headers on 401, 404, and the forced-500.

## Migration Plan

No data migration. Config gains `server.trusted_proxies` via the versioned
config migration (FRG-DEP-004). Rollout is inert for direct-connection
deployments; proxy operators opt in post-upgrade. Rollback = ordinary
version rollback; no persisted state changes.

## Open Questions

None blocking. The FRG-DEP-012 re-accept-vs-implement recommendation (§6)
is surfaced for the owner at approval.
