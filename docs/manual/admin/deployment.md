# Deployment

**Status: forthcoming.** No Docker image exists yet as of this writing. Docker
packaging is scoped to OpenSpec change `m1-ui-opds-deploy`, which has not merged to
`main`. This section describes the packaging the specs already commit to
(`openspec/specs/dep/spec.md`), so you know what to expect once that change lands —
none of it is available today.

Until that change merges, run foragerr from source (see the backend `pyproject.toml`
/ `uv` tooling) with the environment variables in `configuration.md` set directly, and
apply the same Tailscale-only exposure posture described in `network.md` yourself.

## Intended packaging (from spec, not yet implemented)

- **Single Docker image, linuxserver.io conventions** (`FRG-DEP-001`): `PUID`/`PGID`
  environment variables mapping the container's runtime user to your host UID/GID,
  a single `/config` volume holding all persistent state, s6-overlay-style (or
  compatible) init, and `TZ` support. Media library and downloads mounts (e.g.
  `/comics`, `/downloads`) are additional volumes that hold no application state of
  their own.
- **Everything persistent lives under `/config`** (`FRG-DEP-002`): database, config
  file, logs, backups, caches. The container filesystem outside `/config` is treated
  as disposable — replacing the container against the same `/config` volume should
  restore identical state with no re-initialization.
- **Health check** (`FRG-DEP-007`): an unauthenticated `GET /health` reporting
  liveness/readiness (database reachable, scheduler running, migration state),
  suitable for Docker `HEALTHCHECK`.
- **Graceful shutdown** (`FRG-DEP-008`): SIGTERM/SIGINT stop new work intake, drain or
  checkpoint in-flight work within a bounded grace period (under 30s), checkpoint the
  SQLite WAL, and exit 0 — compatible with s6/Docker's shutdown expectations.
- **No self-update** (`FRG-DEP-009`): deliberately, in contrast to Mylar. There is no
  git-pull or tarball-fetch upgrade path. Upgrading foragerr means deploying a new
  image against the same `/config` volume — nothing else.
- **Version/build info** (`FRG-DEP-010`): the running instance exposes its version,
  build/commit id, and build date via an API endpoint and the startup log line, so a
  deployed instance is always identifiable.

The intended example invocation, once the image exists:

```bash
docker run \
  -e PUID=1000 -e PGID=1000 -e TZ=Etc/UTC \
  -v ./config:/config \
  -p 8789:8789 \
  foragerr
```

Files created under `/config` should be owned by the `PUID:PGID` you supplied.

## Where to look once this lands

When `m1-ui-opds-deploy` merges, this section will be rewritten with the actual image
name/tag, real compose/run examples, and any deviations from the intended design
above. Until then, treat everything in this section as a forward-looking summary of
committed requirements, not a description of working software.
