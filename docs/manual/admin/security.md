# Deployment security

How to deploy foragerr well. These are the operator-facing projections of
the project's decided security positions — the positions themselves, with
their rationale, live in `docs/security/posture.md` (FRG-DEP-017).

## TLS: terminate it in front of foragerr, never inside

foragerr never terminates TLS. Two supported stories:

- **Tailscale (recommended default)** — every hop is WireGuard-encrypted
  already; use `tailscale serve` if you want a real certificate and
  browser-green HTTPS on the tailnet.
- **Reverse proxy** — Caddy/nginx/Traefik terminating TLS in front of the
  container, per linuxserver.io convention.

If a proxy terminates TLS, tell foragerr about it — see the next section.
Never expose the listener directly to the public internet.

## Behind a reverse proxy: `FORAGERR_TRUSTED_PROXIES`

Behind any TLS-terminating proxy, foragerr itself sees plain HTTP from the
proxy's address. Without configuration it therefore (correctly) refuses to
trust forwarded headers: session cookies are not marked `Secure`, and
rate-limiting/audit see the proxy's address as the client.

Set `FORAGERR_TRUSTED_PROXIES` (or `trusted_proxies` in `config.yaml`) to
the **address of the proxy you run** — comma-separated if there are
several:

```
FORAGERR_TRUSTED_PROXIES=172.18.0.5
```

When a request's *direct peer* is on this list, foragerr honors its
`X-Forwarded-Proto` and `X-Forwarded-For`: login cookies get the `Secure`
flag (they will only travel over HTTPS), and throttling/audit attribute
requests to the real client address instead of the proxy.

**Warning (RISK-052):** set this *only* to the address of a proxy you run.
Any peer on the list can claim an arbitrary scheme and client address —
listing a wrong or shared address re-opens exactly the spoofing the
default refuses. Empty (the default) means forwarded headers are never
consulted. Also set `FORAGERR_AUTH_ORIGIN_ALLOWLIST` if the proxy serves a
different origin — see `authentication.md`.

## Encrypt the disk, not the database

Provider credentials you enter in the UI are already encrypted at rest
(under your `FORAGERR_SECRET_KEY`), the admin/OPDS passwords and API keys
are stored as one-way hashes, and library metadata is plain data. foragerr
deliberately does **not** encrypt the whole database — on a compromised
live host the key would sit right next to it and protect nothing.

What the application structurally cannot protect is the host itself — so
use **full-disk encryption** on the server that runs foragerr, and make
`FORAGERR_SECRET_KEY` a long generated value (see `secrets.md`), because a
weak passphrase is what makes a stolen encrypted blob crackable offline.

## Container run flags

The application needs no special privileges. Recommended compose stanza:

```yaml
services:
  foragerr:
    image: foragerr
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:          # the s6 init needs these to drop to PUID/PGID
      - CHOWN
      - SETUID
      - SETGID
      - DAC_OVERRIDE
```

A read-only root filesystem (`read_only: true` + tmpfs for `/run`,`/tmp`)
is compatible with the image if you accept the s6-overlay trade-offs;
`/config` stays a writable volume either way. Keep PUID/PGID remapped to
an unprivileged user (see `deployment.md`).

## What unauthenticated callers see

By design, almost nothing: `/health` answers credential-free for Docker
health checks, but its body is only an overall status (plus failing
component *names* when unhealthy). The detailed component view —
migration state, task lists, diagnostics — moved behind authentication at
`/api/v1/system/health/components`; the System → Health screen uses it. If
you previously scraped `/health` for detail, authenticate with an API key
and use the components endpoint instead.

Error responses never contain tracebacks or internal paths; there is no
debug switch that changes that.

## Downgrading

Rolling back below **v0.9.0** re-opens security posture you now rely on:
v0.7.0 introduced mandatory authentication, v0.9.0 completed failed-login
throttling and the audit trail. Pin your image, and treat any downgrade
below v0.9.0 as re-exposing an unauthenticated-era listener — do it only
disconnected from the network, if at all. See also `authentication.md` →
"Downgrading".
