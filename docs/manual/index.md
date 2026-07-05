# foragerr manual

This is the user and administrator manual for foragerr, a private, Sonarr-style comic
management tool. It is a controlled artifact under `FRG-PROC-011`: the manual is kept
in sync with the application, matching whatever is merged to `main` — a single rolling
Markdown manual in-repo, not a versioned or published document.

## What this manual covers

- **User guide** (`user/`) — for someone operating the application day to day: adding
  and monitoring series, refreshing metadata, searching indexers, and managing
  downloads.
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
    library.md           add flow, monitoring, root folders
    metadata.md           ComicVine refresh
    search.md              indexers, interactive search
    downloads.md            SABnzbd + built-in DDL, queue, blocklist
    import.md                STUB — pending change m1-import-pipeline
  admin/
    configuration.md      config.yaml, FORAGERR_* env vars
    secrets.md             secrets handling
    network.md              port, Tailscale-only posture, no auth in M1
    deployment.md            Docker packaging (forthcoming)
```

## Currency statement (FRG-PROC-011)

This manual describes application behavior **already merged to `main`** as of the M1
changes through downloads (changes 1-5: foundation, filename parser, library +
metadata, search + indexers, downloads). It does not describe behavior that exists
only in an open change branch or an unmerged proposal.

Per `FRG-PROC-011`, every OpenSpec change proposal from this point forward declares
its manual impact (sections it adds or updates, or an explicit "no manual impact" with
rationale), and a change that alters manual-documented behavior updates the affected
sections in the same change, before merge to `main`. The merge gate checklist
(`docs/process/`) verifies the declared impact was carried out.

Known gaps, deliberately left open pending later changes:

- **Import pipeline** (`user/import.md`) — stubbed; fills in when change
  `m1-import-pipeline` merges.
- **Deployment** (`admin/deployment.md`) — describes the intended Docker packaging from
  the specs but is marked forthcoming; no image exists yet. Fills in when change
  `m1-ui-opds-deploy` merges.
