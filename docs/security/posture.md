# foragerr — Deployment Security Posture (FRG-DEP-017)

The decided security positions of the supported deployment, each with its
rationale and review trigger. This document is the citable authority an
external reviewer (or the M10 pentest scope statement) starts from; the
operator-facing projection lives in the manual
(`docs/manual/admin/security.md`). Where a position is implemented by a
requirement, the requirement id governs; this document records *why the
position is what it is*.

Decided in the m10-go-live pre-design (owner review 2026-07-15) and
implemented/recorded by `m10-deployment-posture` unless noted.

## 1. Transport: TLS is the deployment layer's job

foragerr never terminates TLS. The supported stories are **Tailscale**
(WireGuard encryption on every hop; `tailscale serve` where real
certificates are wanted) and a **reverse proxy** per linuxserver.io
convention. In-app TLS (certificate loading, renewal, cipher configuration)
is **rejected**: it is new attack surface and new SOUP for a capability the
supported deployment already gets from its network layer.

- Behind a TLS-terminating proxy, set `trusted_proxies` (FRG-SEC-007) so
  session cookies carry `Secure` and rate-limit/audit attribution sees the
  real client. Only when the *direct peer* is on that list are
  `X-Forwarded-Proto` / `X-Forwarded-For` honored; the default (empty) never
  consults them.
- **Review trigger**: any change to session-cookie attributes, the rate
  limiter's keying, or audit attribution re-reads this position.

## 2. At-rest: three storage classes, credentials-only encryption

- **Encrypted** — UI-entered provider secrets and the Humble session cookie:
  `enc:v1:` Fernet under a scrypt-derived key from the env-only
  `FORAGERR_SECRET_KEY` (FRG-AUTH-008/011/012/013). Write-only API; log
  redaction self-registration.
- **Hashed, deliberately not encrypted** — the admin password (scrypt),
  foragerr API keys (SHA-256), session tokens. These are verify-only values:
  *nothing to decrypt* is strictly stronger than encryption here.
- **Plaintext by design** — library metadata (series, issues, paths): not
  sensitive. Known exception: an operator-placed `config.yaml` key remains
  operator-file trust class (RISK-041).

**Full-database encryption is rejected.** Against the stolen-file threat the
keystore already covers the sensitive subset; against live-host compromise a
SQLCipher key would sit in the same environment on the same host and add
nothing but SOUP. **Full-disk encryption is recommended** to operators
instead — host encryption protects exactly what the application structurally
cannot (the environment, the running host). Residual: a weak operator
passphrase lowers offline brute-force cost (RISK-041); the manual recommends
a generated value.

- **Review trigger**: any new stored credential class, or a multi-user
  milestone, re-opens this section.

## 3. Inbound resource envelope (DoS)

Implemented by FRG-NFR-014 (`api/limits.py` + the WebSocket caps): streaming
request-body cap (413, no whole-body buffering even against a lying
`Content-Length`), header-size cap (431), time-to-first-byte request timeout
(503, never truncating a started stream), per-client sliding-window rate cap
(429 + `Retry-After`, LRU-bounded table), WS connection/inbound caps. All
operator-configurable with generous defaults.

**Archive-memory residual (RISK-005 position, restated):** stdlib `zipfile`
materialises central-directory entries at open time, so a hostile archive
can consume memory before the member cap rejects it. Bounded by on-disk
size, the single-operator/curated-library posture, and the archive-layer
caps (FRG-SEC-003); a streaming central-directory guard remains recorded
future hardening, deliberately not 1.0 scope.

## 4. Browser surface

- **Security response headers on every response** (FRG-SEC-006): nosniff,
  `Referrer-Policy: same-origin`, `frame-ancestors 'none'` (+
  `X-Frame-Options: DENY` fallback). CSP is per-surface: data responses
  (API/OPDS/health) carry `default-src 'none'`; the SPA document carries a
  self-only policy.
  - **Recorded loosening**: the SPA policy includes `style-src
    'unsafe-inline'` — React styles elements through inline `style`
    attributes, which CSP governs under `style-src`. Scripts remain
    `'self'`-only, which is where CSP's XSS value lives. Review trigger: a
    frontend toolchain change that emits hashed/nonce'd styles retires this.
- **No CORS, by position**: the application is same-origin only; no
  `Access-Control-Allow-*` header is ever emitted (test-asserted). A future
  cross-origin consumer is a spec change, not a config flag.
- **CSRF**: SameSite=Lax cookies plus the Origin check on state-changing
  requests and the WebSocket handshake (FRG-SEC-005), unchanged here.

## 5. What unauthenticated callers can learn

As little as the container contract allows (FRG-SEC-008):

- `/health` (the one auth-exempt route besides login): overall status, plus
  failing component *names* when unhealthy. No paths, versions, revisions,
  task lists, or error text — that detail requires authentication
  (`/api/v1/system/health/components`).
- Unhandled errors: the uniform generic envelope, traceback to the
  server-side structured log only. No debug flag exists in the packaged
  application.
- Perimeter 401s: the uniform envelope, no username/key-format hints.

## 6. Container runtime

The manual recommends: `--security-opt no-new-privileges`, `cap_drop: ALL`
(the linuxserver.io s6 init needs the defaults it re-adds itself — see the
manual for the exact compose stanza), a read-only rootfs where the operator
accepts the s6 trade-offs, and PUID/PGID remapping (FRG-DEP-002 volumes).
These are deployment-layer controls: recommended and documented, not
enforced by the application.

## 7. Downgrade warning

Rolling back below **v0.9.0** reopens the pre-auth-throttling posture
(RISK-020's mitigation history): v0.7.0 introduced the perimeter, v0.9.0
completed throttling and audit. The manual's upgrade section carries the
warning; a startup version-regression refusal was considered and deferred
(noted enhancement, not 1.0 scope — the operator who pins images per the
manual never hits it silently).

## 8. Aged residual decisions (2026-07-17)

- **FRG-DEP-012 (secrets-stripped diagnostic bundle)** — remains backlog,
  formally re-accepted: 1.0 needs no support-bundle feature (single
  operator, structured logs already redact). Review trigger: the first real
  support case that would have needed one.
- **RISK-008 (DDL `extractall` hardening)** — re-affirmed dormant: no
  `extractall` exists anywhere in the codebase; the DDL path lands single
  files only. Review trigger: any change introducing archive *extraction*
  (as opposed to the read-only member streaming of FRG-SEC-003).
