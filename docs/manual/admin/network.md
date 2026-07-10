# Network exposure

## Listener

foragerr's HTTP listener binds to `host`/`port` (`FORAGERR_HOST` / `FORAGERR_PORT`,
defaults `0.0.0.0` and `8789`). Inside a container, the default all-interfaces bind
means the port is reachable however you choose to publish it — the actual exposure
boundary is up to you (see below).

## No authentication — an accepted risk

**foragerr currently ships with no authentication on the web UI, API, or OPDS
surfaces.** This is a deliberate, owner-approved decision, not an oversight.
Replacing this posture with real authentication is tracked in
[the roadmap](../../roadmap.md), not a shipped capability.

- Requirement `FRG-AUTH-001` states that the system operates without credentials
  on every surface. There is no partial or dormant auth code path to accidentally
  rely on — a route-inventory test asserts no auth middleware or dependency is
  registered on any route.
- This is recorded in `docs/security/risk-register.md` as **RISK-020**
  (Spoofing/Elevation, impact H, likelihood H), explicitly **accepted** by the project
  owner, with a stated review trigger: *any exposure beyond the tailnet, or before
  authentication is added*.
- The compensating control is **Tailscale-only network exposure**
  (`FRG-DEP-011`): foragerr is operated as reachable only via the home server's
  Tailscale network. There is no requirement for it to be safe to expose to
  the public internet while it has no authentication.

### What this means operationally

**Do not** publish foragerr's port to the public internet, a shared LAN you don't
fully trust, or any reverse proxy without its own access control. The only supported
pre-auth exposure model is:

1. Run foragerr on your home server.
2. Join that server to your Tailscale network (tailnet).
3. Reach foragerr only via its Tailscale address (or a Tailscale-scoped hostname),
   from devices also on that tailnet — including the iPad you intend to read from via
   OPDS.

If you widen exposure beyond the tailnet before authentication exists, you are
operating outside the accepted-risk boundary recorded in the risk register, and should
treat that as a decision requiring its own review, not an incidental config change.

### Endpoints that answer without credentials

The `/health` endpoint (`FRG-DEP-007`) answers without credentials by design — it
exists for container health checks (Docker `HEALTHCHECK`) and must respond
regardless of any authentication configuration.

## Related security posture

For the full threat analysis behind this decision, see `docs/security/threat-model.md`
and `docs/security/risk-register.md`. Outbound requests (to ComicVine, indexers,
SABnzbd, GetComics) are separately hardened with connect/read timeouts, TLS
verification, and egress/SSRF controls — those protect foragerr's outbound traffic,
not its listener; they are unrelated to the inbound no-auth posture described here.
