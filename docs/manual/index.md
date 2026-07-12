# foragerr manual

This is the user and administrator manual for foragerr, a self-hosted, Sonarr-style
comic library management tool. It is a controlled artifact under `FRG-PROC-011`: the manual is kept
in sync with the application, matching whatever is merged to `main` — a single rolling
Markdown manual in-repo, not a versioned or published document.

## What this manual covers

- **User guide** (`user/`) — for someone operating the application day to day: adding
  and monitoring series, refreshing metadata, searching indexers, managing downloads,
  importing files, using the web UI, and reading over OPDS.
- **Admin guide** (`admin/`) — for someone deploying and configuring the application:
  configuration file and environment variables, secrets handling, network exposure,
  and deployment.

For the project's purpose, security posture, and way of working, see the repository
[`README.md`](../../README.md).

## Structure

```
docs/manual/
  index.md              this file
  user/
    library.md           add flow, monitoring, root folders, series management
    metadata.md           ComicVine refresh, lookup troubleshooting, cover art
    search.md              indexers, interactive search, decision engine
    downloads.md            SABnzbd + built-in DDL, queue, blocklist
    import.md                import pipeline, manual import, ComicInfo, recycle bin
    sources.md                store sources (Humble Bundle): connect, sync, review
    web-ui.md                 the web interface, screen by screen
    reading-opds.md            OPDS catalog for reading on a tablet
  admin/
    configuration.md      config.yaml, FORAGERR_* env vars
    secrets.md             secrets handling
    authentication.md       mandatory login, bootstrap credentials, sessions
    network.md              port, Tailscale-only posture, authentication
    deployment.md            Docker image build, run, upgrade
```

## Currency statement (FRG-PROC-011)

This manual describes application behavior **already merged to `main`**. As of the
last update to this statement, that is everything through M1 (v0.1.x: foundation,
filename parser, library + metadata, search + indexers, downloads, import pipeline,
UI + OPDS + deployment, integration/e2e), M2 (v0.2.x: configuration, manual
import + ComicInfo tagging, existing-library import, daily-use surfaces,
scheduled backups + System screens, hardening/performance), M3 (v0.3.x: OPDS
page streaming, franchise volume grouping, collected-edition typing, the
public-repository posture), and the M4 changes merged so far (v0.4.x: the
design refresh's app shell and library views, the logs viewer, and the
redesigned series detail with trade containment).
It does not describe behavior that exists only in an open change branch or an
unmerged proposal.

Per `FRG-PROC-011`, every OpenSpec change proposal declares its manual impact
(sections it adds or updates, or an explicit "no manual impact" with rationale), and
a change that alters manual-documented behavior updates the affected sections in the
same change, before merge to `main`. The merge gate checklist (`docs/process/`)
verifies the declared impact was carried out.

No chapters are currently stubbed. Every milestone that has added user-visible
surface so far (library import, wanted/history screens, backups/restore/System
screens) landed its chapter or section in the same change that merged the
behavior.
