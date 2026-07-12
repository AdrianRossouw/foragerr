# Authentication

foragerr requires a login on **every** surface — the web UI, the REST API, the
OPDS catalog, and the WebSocket. There is no unauthenticated mode: a
default-deny check runs in front of every route, and the only two things it
lets through without a credential are the container's `/health` liveness probe
and the login screen itself (the static SPA shell that renders it — every API
call the shell makes is still authenticated).

This page covers bootstrapping the one operator account, the three credential
types, session behaviour, and the reverse-proxy Origin allowlist.
`network.md` covers the exposure-model framing (why Tailscale-only is still
the recommended default even though a login now exists);
`secrets.md` covers the wider "environment trust class" these bootstrap
variables belong to.

## First boot: the mandatory bootstrap pair

**Breaking change.** From this release, foragerr refuses to start on a fresh
deployment (no account exists yet) unless both of these are set:

| Env var | Purpose |
|---|---|
| `FORAGERR_ADMIN_USER` | Bootstrap operator username. |
| `FORAGERR_ADMIN_PASSWORD` | Bootstrap operator password (secret; never written to `config.yaml`). |

If either is missing, startup fails fast — before migrations or any data
access — with an error naming both variables and a one-line compose fix, the
same pattern as the mandatory `FORAGERR_SECRET_KEY` check
(`secrets.md`). For example:

```yaml
environment:
  FORAGERR_ADMIN_USER: admin
  FORAGERR_ADMIN_PASSWORD: "${FORAGERR_ADMIN_PASSWORD}"   # openssl rand -base64 24
```

On the first boot that has this pair, foragerr seeds a single operator
account: the web login credential, an OPDS HTTP-Basic credential, and a
programmatic API key (see below). There is only ever one account — foragerr
is a single-operator tool; multi-user support is not in scope.

### Optional: a separate OPDS password

```
FORAGERR_OPDS_PASSWORD=...
```

If set, this becomes the password OPDS readers authenticate with, independent
of the admin password. If left unset, the OPDS password **equals the admin
password** at seed time. Changing the OPDS password independently later (a
Settings screen) is planned for a follow-up release; until then, the only way
to change it is the recovery path below (which also affects the admin
password).

### Lost password / lockout recovery

There is no "forgot password" flow in the UI (there is only one account, and
its administrator is the one person who can edit the deployment's
environment). Recovery is deliberate: **set a new `FORAGERR_ADMIN_USER` /
`FORAGERR_ADMIN_PASSWORD` pair and restart the container.**

On any boot after the first, foragerr compares the current environment pair
against the stored account:

- **Unchanged** (same username, and the password still verifies) — idempotent
  no-op. This is the normal case on every ordinary restart.
- **Changed** (different username, or a password that no longer verifies) —
  foragerr re-seeds the account from the new pair and **signs out every
  existing session**. This is the recovery path: if you're locked out, you get
  back in by changing the environment, not by resetting anything in the app.
  The re-seed is logged (username change and session count, never the
  password) so it's visible after the fact.

Re-seeding does **not** rotate the OPDS password (unless `FORAGERR_OPDS_PASSWORD`
also changed) or the API key — see the API key section below for what a
re-seed does and doesn't affect.

## Credentials by surface

One account, three credential forms, verified independently per surface:

| Surface | Credential | Transport |
|---|---|---|
| Web UI (and its own API calls) | Session, from form login | `foragerr_session` cookie (HttpOnly, `SameSite=Lax`) |
| Programmatic API (scripts, `curl`, automation) | API key | `X-Api-Key` request header — **header only, never a query parameter** |
| OPDS (reading apps) | OPDS username/password | HTTP Basic, its own realm |

### Web UI: login, remember-me, logout

Opening foragerr while signed out shows a minimal login screen: username,
password, and a **"Remember this device"** checkbox. Signing in without the
checkbox starts a standard session (sliding, expires after a period of
inactivity); checking it starts a longer-lived remember-me session (also
sliding). Both durations are configurable:

| Setting | Env var | Default | Notes |
|---|---|---|---|
| `session_timeout_seconds` | `FORAGERR_SESSION_TIMEOUT_SECONDS` | `86400` (24 h) | Standard session sliding-inactivity window. Each authenticated request pushes the expiry forward. |
| `remember_timeout_seconds` | `FORAGERR_REMEMBER_TIMEOUT_SECONDS` | `7776000` (90 d) | Remember-me sliding window. A default, not a floor — lower it if the device is shared. |

A **logout** button lives in the app header (the same area as the Health and
System quick-access buttons — see `../user/web-ui.md`); it deletes the
session server-side, so the token can't be replayed even if the cookie leaks
afterward. Logging in always issues a brand-new session token, so a token
that existed before you signed in (for example, one an attacker planted) never
survives login.

### Programmatic API: the `X-Api-Key` header

Scripts and automation authenticate with the API key generated at bootstrap,
sent as a header on every request:

```bash
curl -H "X-Api-Key: <your-api-key>" http://<host>:8789/api/v1/series
```

The key is **never** accepted as a query parameter — only the header. It is
shown to you exactly **once**, right after the first boot that seeds the
account: log in through the web UI (or with `curl` against the login route),
then call:

```bash
curl -c cookies.txt -X POST http://<host>:8789/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<your-admin-password>"}'

curl -b cookies.txt -X POST -H "Origin: http://<host>:8789" \
  http://<host>:8789/api/v1/auth/bootstrap-key
# {"api_key": "..."}
```

Retrieving the key is a `POST` (the read consumes the one-time key), so under
cookie authentication it needs an `Origin` header matching your deployment —
the same cross-site-request protection every state-changing call carries.

That endpoint answers **once per boot** — the key is held only in the
running process's memory (never logged, never written to disk in plaintext),
and the first successful read clears it. A second call, or a call after a
restart, returns 404. **Save the key somewhere durable as soon as you retrieve
it.** If you don't, there is currently no way to see it again or generate a
replacement — key display and rotation from Settings are planned for a
follow-up release. Re-seeding the account (the lost-password recovery path
above) does **not** regenerate or reveal the API key either; it only affects
the login/OPDS credentials.

The interactive API documentation (Swagger UI / ReDoc) that FastAPI serves by
default is turned off, since those routes bypass the perimeter. The raw
OpenAPI schema is still available at `GET /api/v1/openapi.json`, but — like
every other API route — it now requires a credential (session cookie or
`X-Api-Key`).

### OPDS: HTTP Basic

Point your reading app at the catalog with the admin username and the OPDS
password (equal to the admin password unless you set
`FORAGERR_OPDS_PASSWORD`):

```
http://<username>:<opds-password>@<host>:8789/opds
```

Most reading apps instead prompt for username/password the first time they
connect and store it themselves — see `../user/reading-opds.md`. A bare
request to `/opds` gets a `401` with a `WWW-Authenticate: Basic` challenge
naming the `foragerr-opds` realm, so a reader that supports Basic auth will
prompt automatically without any special configuration.

## Reverse proxies and the WebSocket Origin check

Every state-changing request authenticated by the session cookie, and every
WebSocket handshake, is checked against an Origin allowlist (defense against
cross-site request forgery and cross-site WebSocket hijacking). By default
the only allowed Origin is the deployment's own — derived from the request's
`Host` header, both `http://` and `https://` since TLS termination may happen
in front of foragerr. If you run foragerr behind a reverse proxy whose public
hostname differs from what foragerr sees, add it to the allowlist:

| Setting | Env var | Default | Notes |
|---|---|---|---|
| `auth_origin_allowlist` | `FORAGERR_AUTH_ORIGIN_ALLOWLIST` | *(empty)* | Comma-separated extra allowed Origins, e.g. `https://comics.example.org`. Own-origin is always allowed in addition to this list. |

A GET/HEAD request is never subject to the Origin check (it can't change
state). A `POST`/`PUT`/`PATCH`/`DELETE` authenticated by the session cookie
with a foreign or absent Origin/Referer is refused with `403` before it
reaches the handler. The `X-Api-Key` surface is exempt from this check
entirely — a browser cannot attach a custom header cross-site, so it's not a
CSRF vector.

The live-updates WebSocket (`/api/v1/ws`) runs the same credential check (a
valid session cookie or `X-Api-Key`) plus the Origin allowlist, refusing the
connection **before** it upgrades — a rejected socket looks like a failed
connection attempt in the browser, not a readable close code.

## Downgrading

Rolling a deployment back to a release before this one re-opens the
unauthenticated surface this release closes: a pre-auth build has no login at
all, on any route. If you ever need to run an older image against the same
`/config` volume, treat that as a deliberate return to the pre-auth exposure
model (Tailscale-only, as documented in `network.md`) for as long as the
older build is running.

## Related

- `network.md` — exposure-model framing now that a login exists.
- `secrets.md` — the environment trust class the bootstrap credentials
  belong to, alongside `FORAGERR_SECRET_KEY`.
- `configuration.md` — the full settings reference, including the auth rows
  above.
- `deployment.md` — the compose example with the bootstrap variables in
  place.
- `../user/web-ui.md` — the login screen and logout button from the operator's
  side.
- `../user/reading-opds.md` — connecting an OPDS reader with its Basic
  credential.
