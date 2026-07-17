# m10-deployment-posture — headers, trusted proxy, disclosure hygiene, posture record

First implementing change of M10 go-live (owner reorder 2026-07-17:
hardening lands before the release pipeline), per the milestone pre-design
(`change/m10-go-live`, design authority §1 Transport posture, §2 At-rest
posture, §9 Hardening sweep).

## Why

M10's bar is "safe for strangers to deploy", and the pentest (final M10
change) will judge the deployment posture — this change fixes the real gaps
first and converts de-facto positions into committed, citable decisions, so
delegated controls land as reasoned positions rather than findings. Three
gaps are verified in current code: session cookies never set `Secure` behind
a TLS-terminating proxy (`auth/routes.py` keys on the scheme the app sees —
plain HTTP behind any proxy); no HTTP security response headers are set on
any surface; and the unauthenticated `/health` body discloses the database
filesystem path, migration revisions, the scheduler task list, and raw
exception strings to anyone who can reach the port.

## What Changes

- **HTTP security response headers** on every surface (API, OPDS, SPA,
  health): Content-Security-Policy (self-contained SPA — no external
  origins), `X-Content-Type-Options: nosniff`, `frame-ancestors 'none'` (+
  `X-Frame-Options` fallback), and a restrictive `Referrer-Policy`. The
  deliberate absence of CORS middleware (same-origin only) is stated as a
  position, with a test asserting no `Access-Control-Allow-*` ever appears.
- **Opt-in trusted-proxy handling**: a config setting naming the proxy
  address(es) an operator runs; only when the direct peer matches are
  `X-Forwarded-Proto`/`X-Forwarded-For` honored — fixing the Secure-cookie
  gap and, by the same setting, revising the rate limiter's and audit log's
  documented X-Forwarded-For refusal so cookie flags and IP attribution stay
  consistent. Default (no proxy configured) behavior is byte-for-byte
  unchanged: direct peer only, forwarded headers ignored.
- **Unauthenticated disclosure hygiene**: `/health` slims to overall status
  plus failing component *names* only — no paths, revisions, task lists,
  version strings, or exception text; the full component detail moves behind
  authentication on the system surface. Unhandled errors return a generic
  500 with no traceback or debug detail on any surface, asserted by test;
  there is no debug flag that can enable disclosure in the packaged image.
- **Deployment security posture record**: a committed posture document
  stating the decided positions — TLS is the deployment layer's job
  (Tailscale / reverse proxy, never in-app); the three at-rest storage
  classes (encrypted credentials, hashed verify-only data, plaintext
  library metadata) with full-database encryption **rejected** with
  rationale and full-disk encryption recommended to operators; the DoS
  envelope as implemented (FRG-NFR-014 listener limits, WS caps) with the
  zipfile-OOM position restated against RISK-005; the no-CORS position; and
  a downgrade warning (rolling back below v0.9.0 reopens the
  auth-throttling gap). The manual gains a deployment-security section:
  TLS stories, FDE recommendation, container run flags
  (`no-new-privileges`, `cap_drop`, read-only rootfs guidance), trusted
  proxy configuration and its misconfiguration risk.
- **Aged residuals decided** (decide-and-document, no new ids):
  FRG-DEP-012 (diagnostic bundle, approved-for-backlog since M1) and
  RISK-008 (DDL extractor hardening) are each implemented or formally
  re-accepted with recorded rationale and review triggers in this change —
  a three-milestone-old backlog row reads worse than an explicit decision.

## Capabilities

### New Capabilities

None — both affected areas have existing specs.

### Modified Capabilities

- `sec`:
  - **ADDED** `FRG-SEC-006 — HTTP security response headers` (CSP, nosniff,
    frame-ancestors, Referrer-Policy; no-CORS position test-asserted).
  - **ADDED** `FRG-SEC-007 — Opt-in trusted-proxy handling` (forwarded
    headers honored only from a configured proxy peer; governs cookie
    Secure flag and client-IP attribution together).
  - **ADDED** `FRG-SEC-008 — Unauthenticated disclosure and error hygiene`
    (generic 500s, no tracebacks, no debug disclosure path, minimal
    unauthenticated health).
- `dep`:
  - **MODIFIED** `FRG-DEP-007 — health endpoint` (unauthenticated body
    minimized to overall status + failing component names; full detail
    moves behind auth; complete scenario set restated).
  - **ADDED** `FRG-DEP-017 — Documented deployment security posture`
    (posture document + manual deployment-security section, kept in sync
    with the decided positions).

IDs FRG-SEC-006/007/008 and FRG-DEP-017 are allocated in
`docs/traceability/requirements-registry.md` by this proposal. (FRG-DEP-015
and FRG-DEP-016 are already allocated to the sibling `m10-release-pipeline`
proposal; this change deliberately skips them.)

## Impact

- **Attack surface** (FRG-PROC-006, security docs in this change): headers
  middleware is low-risk new surface; the trusted-proxy setting is a
  **deliberate revision** of the documented X-Forwarded-For trust refusal —
  the misconfiguration risk (trusting a spoofable header when the
  configured address is wrong) gets a risk-register row, and the manual
  states plainly: set this only to the address of a proxy you run. Health
  minimization *reduces* surface; STRIDE information-disclosure rows update
  accordingly. RISK-005 (zipfile), RISK-008, and the FRG-DEP-012 decision
  are re-recorded with current rationale.
- **Code**: headers + trusted-proxy middleware in the backend perimeter
  area; `/health` handler and system-surface detail endpoint; error-handler
  hardening test; config settings (trusted proxy) with FRG-DEP-004
  config-migration handling.
- **Docs** (FRG-PROC-011): new posture document under `docs/security/`;
  manual deployment-security section; README labelling untouched;
  `docs/roadmap.md` M9-complete/M10-in-progress touch moves into this
  change (it lands first).
- **Compatibility**: no breaking change for direct-connection deployments
  (default behavior unchanged). Operators previously scraping `/health` for
  component detail must authenticate for it — called out in the CHANGELOG
  upgrade notes.

## Non-goals

- In-app TLS termination or certificate management (rejected position,
  recorded in the posture document).
- Full-database encryption (rejected with rationale — the keystore already
  covers the sensitive subset; SQLCipher adds SOUP, not protection, against
  the live-host threat).
- Release pipeline, GHCR publishing, channels, change control — the sibling
  `m10-release-pipeline` change (second).
- IQ/OQ/PQ machinery — `m10-vnv-qualification` (this change feeds it
  checklist items).
- A startup version-regression refusal for downgrades (manual warning only;
  noted as a possible future enhancement).
- Auth changes: the perimeter, session, and throttling designs are
  untouched — this change only adjusts what unauthenticated responses
  disclose and when cookies carry `Secure`.

## Approval

**Approved by Adrian, 2026-07-17** — owner directive in session: hardening
reordered to first M10 change ("can we move the hardening first?"), then
"complete the hardening, and then let's discuss the next change", given
against this proposal's presented scope. Milestone-level posture decisions
(TLS delegation, credentials-only at-rest + FDE recommendation,
full-DB-encryption rejection) were reviewed 2026-07-15 in the m10-go-live
pre-design. Design §6's FRG-DEP-012 recommendation (formal re-accept with a
support-case review trigger, not implementation) proceeds as recommended;
it remains owner-reversible as its own future change._
