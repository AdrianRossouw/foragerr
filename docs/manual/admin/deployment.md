# Deployment

foragerr ships as a single Docker image built to linuxserver.io conventions: one
`/config` volume for all persistent state, `PUID`/`PGID`/`TZ` environment variables,
an unauthenticated `/health` endpoint for the container health check, and a graceful
SIGTERM shutdown. The image serves everything on one port (`8789`): the web UI at `/`,
the API at `/api`, the OPDS catalog at `/opds`, and the health probe at `/health`.

> **Read `network.md` first.** foragerr has **no authentication**
> (`FRG-AUTH-001`, an owner-accepted risk — `RISK-020`). Its only supported exposure
> model is **Tailscale-only**. The compose example below binds the listener to the
> host's tailnet address for that reason. Do **not** port-forward foragerr to the
> public internet or an untrusted LAN. See "Network exposure" below and `network.md`
> for the full posture.

## Building the image

There is no published registry image — build it from the repository:

```bash
tools/build-image.sh --tag foragerr:latest
```

The build script secret-scans the build context before invoking `docker build` and
**refuses to build** on key-shaped material in any file that would ship, or on an
env file that `.dockerignore` does not exclude from the context (a `.env` in the
working tree is normal on a dev machine and is reported but non-fatal, because the
recursive `.dockerignore` patterns keep it out of every image layer)
(`FRG-DEP-001`). Run just the scan with `tools/build-image.sh --scan-only`. Under the
hood it is an ordinary multi-stage `docker build` (a node stage builds the frontend, a
`python:3.12-slim` stage installs the backend with `uv` and copies in the built SPA),
so `docker build -t foragerr:latest .` works too — but prefer the script so the secret
scan always runs.

## Running the container

```bash
docker run -d \
  --name foragerr \
  -e PUID=1000 -e PGID=1000 -e TZ=Europe/Amsterdam \
  -v /srv/foragerr/config:/config \
  -v /srv/media/comics:/comics \
  -v /srv/downloads:/downloads \
  -p 100.x.y.z:8789:8789 \
  foragerr:latest
```

The port binding is deliberately prefixed with the host's **tailnet address**
(substitute your own `100.x.y.z`) — a bare `-p 8789:8789` would publish the
unauthenticated listener on every host interface. This is the RISK-020
compensating control; it is not optional (see `network.md`).

Files created under `/config` are owned by the `PUID:PGID` you supply — the container
drops root at startup and runs the application as that unprivileged user. See the
exposure warning below before publishing the port anywhere but the tailnet.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PUID` | `911` | Host user id the app runs as; owns everything it writes under `/config`. Set it to the uid that owns your bind mounts. |
| `PGID` | `911` | Host group id the app runs as (as above). |
| `TZ` | `Etc/UTC` | Container timezone (IANA name, e.g. `Europe/Amsterdam`). Affects log timestamps and scheduling display. |

All other configuration uses the `FORAGERR_*` environment variables and
`config.yaml` documented in `configuration.md`; `FORAGERR_CONFIG_DIR` is fixed to
`/config` inside the image and should not be changed. API keys and other secrets are
covered in `secrets.md` — pass them as `FORAGERR_*` environment variables or place
them in `config.yaml` under `/config`, never bake them into the image.

### The `/config` volume

Everything persistent lives under `/config` (`FRG-DEP-002`): the SQLite database, the
generated `config.yaml`, logs, backups, and caches. The container filesystem outside
`/config` is disposable. **Upgrading** foragerr means building a new image and
recreating the container against the same `/config` volume — there is no in-app
self-update (`FRG-DEP-009`), and no other state to migrate. Releases are annotated
git tags on `main` (`v0.1.0`, `v0.2.x`, ...); to build a specific release, check the
tag out and run `tools/build-image.sh --tag foragerr:<version>`. Destroying and recreating
the container against the same volume restores identical state with no
re-initialisation.

The `/comics` and `/downloads` mounts above are examples — they hold your media and
downloads, not application state, and their paths are whatever you configure. Only
`/config` must persist.

> **BREAKING — set `FORAGERR_SECRET_KEY` before upgrading.** From this release
> foragerr requires the `FORAGERR_SECRET_KEY` environment variable (an
> operator-chosen passphrase) and will refuse to start without it. It encrypts your
> stored provider secrets at rest. When you first upgrade, foragerr transparently
> encrypts any existing plaintext provider secrets in the database under this
> passphrase. Generate a strong value once (`openssl rand -base64 32`), add it to
> your container's environment, and keep it stable across restarts. A changed or
> lost passphrase costs re-entry of your provider secrets (never data) — see
> `secrets.md` → "At-rest encryption of stored provider secrets".

### Health and shutdown

The image declares a Docker `HEALTHCHECK` that probes the unauthenticated
`GET /health` endpoint (`FRG-DEP-007`); the container reports `healthy` once the
database, workers, scheduler, and migration state are all up. On `docker stop`
(SIGTERM) foragerr stops taking new work, drains or checkpoints in-flight work within
a bounded grace period (under 30s), checkpoints the SQLite WAL, and exits cleanly
(`FRG-DEP-008`).

## Restoring from a backup

foragerr writes backups under `/config/backups/` — scheduled `scheduled-*`
backups (daily by default, see `configuration.md` → "Scheduled backups") and
event-triggered `pre-migration-*` / `pre-config-migration-*` safety copies.
There is **no restore button in the running app**: a running foragerr holds
the database file open (single-writer, WAL side files), so safely swapping it
out from under the live process is not possible. Restore is always an
**offline** operation, in one of two supported forms.

### Form 1 — offline file swap (always available)

1. `docker stop foragerr`.
2. Under the `/config` volume, copy the chosen backup's database file and
   `config.yaml` over the live ones (back up the current live files yourself
   first if you want a way back — the app does not do this for you in this
   form).
3. `docker start foragerr`.

This works for any retained backup and needs nothing but file access to the
`/config` volume.

### Form 2 — the `restore-from` startup marker (first-class, automatic)

Instead of copying files yourself, you can ask foragerr to do the swap safely
at its next startup:

1. `docker stop foragerr`.
2. Create a file named exactly **`restore-from`** directly under `/config`
   (i.e. `/config/restore-from`), whose entire contents is the name of the
   backup directory to restore — either just the directory name (e.g.
   `scheduled-20260706120000000000`) or a path, which is always resolved
   **relative to `/config/backups/`**. An absolute path is accepted only if it
   still resolves inside `/config/backups/`; anything that would resolve
   outside it (a `../` escape, or an absolute path elsewhere) is refused, not
   followed.
3. `docker start foragerr`.

On startup, **before** the database engine opens or any migration runs,
foragerr:

1. resolves the marker's target and confirms it is confined under
   `/config/backups/` — a traversal or absolute escape is refused;
2. runs a full integrity check (`PRAGMA integrity_check`) against the named
   backup's database — a corrupt or missing backup is refused;
3. if both checks pass, snapshots the **current** live database and config
   aside to a fresh `/config/backups/pre-restore-<timestamp>/` directory (so a
   botched restore is itself recoverable), clears any stale WAL/SHM files, and
   copies the backup's database and config file into place as the live files;
4. deletes the `restore-from` marker so the restore never repeats on the next
   boot;
5. normal startup then proceeds (migration check → serve) against the
   restored database.

**Refusal is loud and safe.** If the marker names a target outside
`/config/backups/`, or the target's database fails its integrity check, or the
target is missing altogether, foragerr logs the reason at error level, leaves
the marker in place, and boots normally against the **untouched** live
database and config — nothing is swapped, nothing is deleted. Fix or remove
the marker before the next restart; while it remains in place, each start
re-attempts the restore and refuses again harmlessly — the refusal never
touches the live files.

A restore of either form loses any writes made after the backup you chose was
taken — pick the most recent good backup for the smallest gap. The System →
Status screen (see `../user/web-ui.md`) lists the managed paths, including
`/config/backups/`, so you can see what is available before choosing.

## Network exposure

### Tailscale-only is the compensating control

foragerr operates with **no authentication** on the UI, API, and OPDS surfaces.
This is a deliberate, owner-approved decision recorded as **`RISK-020`** in
`docs/security/risk-register.md` ("no auth, network-scoped exposure",
accepted); adding authentication is tracked in
[the roadmap](../../roadmap.md). The **compensating control** is that foragerr is reachable **only over the
home server's Tailscale network** (`FRG-DEP-011`) — that is what keeps the no-auth
posture inside its accepted-risk boundary. Transport security is provided by the
tailnet; foragerr performs no TLS termination of its own.

### Do not port-forward foragerr

**Do not** expose foragerr's port to the public internet, a shared/untrusted LAN, or a
reverse proxy without its own access control. Widening exposure beyond the tailnet
while foragerr has no authentication puts you outside the accepted-risk boundary
in the risk register and is a decision that needs its own review — not an incidental
config change. See `network.md` for the operational detail.

### Tailnet-bound compose example

Bind the published port to the host's **Tailscale address** rather than all
interfaces, so the listener is only reachable from devices on your tailnet (including
the iPad you read from over OPDS). Substitute your server's tailnet IP for
`100.x.y.z`:

```yaml
# docker-compose.yml — foragerr bound to the tailnet, no app TLS.
services:
  foragerr:
    image: foragerr:latest
    container_name: foragerr
    restart: unless-stopped
    environment:
      PUID: "1000"
      PGID: "1000"
      TZ: "Europe/Amsterdam"
      # Secrets come from the host environment / an env_file — never commit them.
      # REQUIRED: the at-rest encryption passphrase. foragerr refuses to start
      # without it. Generate a strong value once (openssl rand -base64 32) and
      # keep it stable across restarts. See secrets.md.
      FORAGERR_SECRET_KEY: "${FORAGERR_SECRET_KEY}"
      FORAGERR_COMICVINE_API_KEY: "${FORAGERR_COMICVINE_API_KEY}"
      # Download-client and indexer credentials (SABnzbd, DogNZB, NZB.su, …) are
      # per-provider settings entered in the UI, not app-wide env vars.
    volumes:
      - /srv/foragerr/config:/config
      - /srv/media/comics:/comics
      - /srv/downloads:/downloads
    ports:
      # Bind ONLY to the tailnet address (100.x.y.z). NOT "8789:8789", which would
      # listen on every interface. NOT a public IP. See RISK-020 above.
      - "100.x.y.z:8789:8789"
```

Because the port is bound to the tailnet interface, foragerr is unreachable from the
public internet or the local LAN even though it has no authentication of its own — the
network boundary is the control. The `FORAGERR_*` secrets are passed as environment
variables (here from the host's environment or an `env_file`); they are never part of
the image.

## Related

- `network.md` — the no-auth posture and Tailscale-only exposure model in full.
- `configuration.md` — every `FORAGERR_*` / `config.yaml` setting, including
  "Scheduled backups" (what a backup contains, retention, the plaintext-
  credentials caveat).
- `secrets.md` — how to supply API keys.
- `../user/web-ui.md` — the System area (Status, Health, Tasks/"Back up now").
- `docs/security/risk-register.md` — `RISK-020` and `RISK-041`, and their
  review triggers.
