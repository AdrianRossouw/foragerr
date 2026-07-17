# sec — delta for m10-deployment-posture

## ADDED Requirements

### Requirement: FRG-SEC-006 — HTTP security response headers

Every HTTP response SHALL carry security response headers set by a single
perimeter middleware wrapping all mounted surfaces (API, OPDS, SPA, health),
including error and exception responses:

- `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, and
  `X-Frame-Options: DENY` on every response;
- a Content-Security-Policy on every response, differentiated by surface:
  the SPA document carries a real policy permitting only self-hosted
  resources (no external origins — the frontend is fully self-contained);
  API, OPDS, and health responses carry a deny-everything policy
  (`default-src 'none'`) with `frame-ancestors 'none'`;
- **no CORS headers, by position**: the application is same-origin only; no
  `Access-Control-Allow-*` header is ever emitted, and this is asserted by
  test. Any future cross-origin need is a spec change, not a config flag.

Loosening the SPA policy (e.g. `style-src 'unsafe-inline'` demanded by the
UI toolchain) SHALL be recorded with rationale in the posture document.

#### Scenario: Baseline headers on every surface

- **WHEN** any response is produced — an API JSON body, an OPDS feed, the SPA document, `/health`, a 401, a 404, or an unhandled-error 500
- **THEN** it carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, and a Content-Security-Policy including `frame-ancestors 'none'` (or the SPA's self-only policy)

#### Scenario: SPA policy is self-contained

- **WHEN** the SPA document response's Content-Security-Policy is inspected
- **THEN** no directive permits an external origin, and the built frontend loads and operates under that policy in the e2e suite

#### Scenario: No CORS surface exists

- **WHEN** any request is made with an `Origin` header from another origin, including a preflight `OPTIONS`
- **THEN** no `Access-Control-Allow-*` header appears in the response

### Requirement: FRG-SEC-007 — Opt-in trusted-proxy handling

Forwarded-request headers SHALL be honored only from explicitly configured
proxy peers, and ignored otherwise. A configuration setting
(`server.trusted_proxies`, default empty) lists the proxy addresses the
operator runs. For a request whose **direct peer** is in the list, the
effective request scheme SHALL be taken from `X-Forwarded-Proto` and the
effective client address from the rightmost non-trusted entry of
`X-Forwarded-For`; for any other request both headers SHALL be ignored.
The effective values SHALL be resolved once, at the perimeter, and used
consistently by every consumer: the session-cookie `Secure` flag (cookies
are `Secure` when the effective scheme is `https`), the listener
rate-limiter's client key (FRG-NFR-014), and the `auth.*` audit log's
client attribution. With the setting empty, behavior is identical to the
prior direct-peer-only posture.

#### Scenario: Secure cookies behind a configured proxy

- **WHEN** `server.trusted_proxies` contains the proxy's address and a login request arrives from that peer with `X-Forwarded-Proto: https`
- **THEN** the session cookies are set with the `Secure` flag, even though the direct connection is plain HTTP

#### Scenario: Forwarded headers from an untrusted peer are ignored

- **WHEN** a request arrives from a peer not in `server.trusted_proxies` carrying `X-Forwarded-Proto` and/or `X-Forwarded-For`
- **THEN** both headers are ignored: the effective scheme is the connection's real scheme, and the rate limiter and audit log attribute the request to the direct peer address

#### Scenario: One resolution, all consumers agree

- **WHEN** a request from a configured proxy is processed
- **THEN** the cookie `Secure` decision, the rate-limiter key, and the audit `client_ip` all reflect the same resolved effective values — no consumer re-derives them from raw headers

#### Scenario: Default posture is unchanged

- **WHEN** `server.trusted_proxies` is unset or empty
- **THEN** request handling is byte-for-byte the prior behavior: direct peer only, forwarded headers never consulted

### Requirement: FRG-SEC-008 — Unauthenticated disclosure and error hygiene

Unauthenticated responses SHALL disclose no internal detail, on any
surface:

- an unhandled server error returns a generic 500 in the standard error
  envelope containing no traceback, no exception class or message text, and
  no filesystem path; the full detail goes to the server-side structured
  log only;
- the packaged application SHALL contain no debug mode or flag that widens
  error disclosure (asserted by test against the app factory);
- the unauthenticated health surface reports at most overall status and
  failing component names (contract owned by FRG-DEP-007); detailed
  component diagnostics require authentication;
- unauthenticated perimeter rejections (401) carry no detail beyond the
  standard envelope — no hint of valid usernames, key formats, or route
  existence variance.

#### Scenario: Unhandled error is generic

- **WHEN** a request handler raises an unexpected exception
- **THEN** the response is a 500 in the standard error envelope with a generic message — no traceback, exception type, message text, or path — and the traceback appears only in the server-side structured log

#### Scenario: No debug disclosure path exists

- **WHEN** the packaged application factory and its configuration surface are inspected by the test suite
- **THEN** no setting, environment variable, or flag enables tracebacks or debug detail in HTTP responses

#### Scenario: Detailed diagnostics require authentication

- **WHEN** an unauthenticated caller requests any health or system-status surface
- **THEN** the response contains no version string, migration revision, filesystem path, task list, or error text; the detailed component view is served only to an authenticated session or API key
