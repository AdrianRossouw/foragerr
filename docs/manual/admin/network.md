# Network exposure

## Listener

foragerr's HTTP listener binds to `host`/`port` (`FORAGERR_HOST` / `FORAGERR_PORT`,
defaults `0.0.0.0` and `8789`). Inside a container, the default all-interfaces bind
means the port is reachable however you choose to publish it — the actual exposure
boundary is up to you (see below).

## Authentication is mandatory

foragerr requires a login on every surface — web UI, API, OPDS, and the
WebSocket. There is no auth-mode-none and no escape hatch; a default-deny
check runs in front of every route, and the only things it lets through
without a credential are the container's `/health` liveness probe and the
login screen itself. See `authentication.md` for bootstrapping the account,
the three credential types (session cookie, API key, OPDS Basic), session
lifetimes, and the reverse-proxy Origin allowlist.

### Tailscale-only exposure — still the recommended default

Even with a login in place, foragerr keeps recommending **Tailscale-only
network exposure** (`FRG-DEP-011`) as the default deployment posture:

- foragerr performs no TLS termination of its own — encryption in transit is
  the tailnet's job (or a reverse proxy's, if you run one in front). Exposing
  the listener beyond the tailnet without TLS in front of it means the login
  cookie and OPDS Basic credential travel in the clear.
- Failed-attempt throttling and structured auth audit events ship as of
  v0.9.0 (see `authentication.md` → "Failed-attempt throttling and the audit
  trail"), but brute-force resistance still leans on the tailnet boundary and
  the credential itself — the throttle is a temporary backoff, not a hard
  lockout, and its per-attacker isolation depends on foragerr seeing real
  client IPs (see the note below).
- This is a single-operator tool: there is no reason to widen its public
  surface, and doing so is a deliberate deployment decision, not an
  incidental config change.

**Do not port-forward or otherwise publish the listener to the
public internet.** Authentication reduces what an internet-facing listener would
expose, but without TLS in front of it your credentials would still travel in
the clear.

### Failed-attempt throttling needs real client IPs

foragerr's failed-login throttling keys on the **direct TCP peer address**
(`request.client.host`); it never trusts `X-Forwarded-For`. That keeps an
attacker from impersonating many source IPs, but it means the isolation
between clients is only as good as the address foragerr actually sees:

- **Docker bridge networking with the userland proxy** (the default for a
  plain `ports:` mapping) can make *every* external client appear to come from
  the bridge gateway address (e.g. `172.17.0.1`). All clients then share one
  throttle key, so a burst of failed logins from anyone on the tailnet can
  temporarily 429 your own login until the backoff deadline passes. It is
  never a permanent lockout (a restart or the deadline clears it, and the
  OPDS/API surfaces stay independent), but the per-attacker isolation is lost.
- To keep the isolation real, run the container so it observes genuine peer
  IPs: `network_mode: host`, Tailscale *inside* the container, or a
  source-preserving DNAT (Docker daemon `userland-proxy: false`). On a
  single-host tailnet deployment `network_mode: host` is the simplest.

### What this means operationally

1. Run foragerr on your home server.
2. Join that server to your Tailscale network (tailnet).
3. Reach foragerr only via its Tailscale address (or a Tailscale-scoped hostname),
   from devices also on that tailnet — including the iPad you intend to read from via
   OPDS.

If you do run foragerr behind a reverse proxy with its own TLS termination,
see `authentication.md` → "Reverse proxies and the WebSocket Origin check"
for the one setting (`FORAGERR_AUTH_ORIGIN_ALLOWLIST`) that needs to know
about it.

### Endpoints that answer without credentials

The `/health` endpoint (`FRG-DEP-007`) answers without credentials by design — it
exists for container health checks (Docker `HEALTHCHECK`) and must respond
regardless of any authentication configuration. The login screen (and the
static assets it needs to render) is the only other unauthenticated route —
every API call the screen itself makes is still authenticated.

### Downgrading

Rolling back to a release before mandatory authentication shipped re-opens
the unauthenticated posture this page used to describe, on any route. See
`authentication.md` → "Downgrading".

## Related security posture

For the full threat analysis, see `docs/security/threat-model.md` and
`docs/security/risk-register.md`. Outbound requests (to ComicVine, indexers,
SABnzbd, GetComics) are separately hardened with connect/read timeouts, TLS
verification, and egress/SSRF controls — those protect foragerr's outbound
traffic, not its listener; they are unrelated to the inbound authentication
posture described here.
