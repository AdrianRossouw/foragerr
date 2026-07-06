# nfr — delta for m2-ops-health-backups

## MODIFIED Requirements

### Requirement: FRG-NFR-011 — observable component health

The system SHALL track and expose per-component health (ComicVine, each indexer, SAB/download clients, DDL provider, scheduler, database, root folders, disk space) with last-success/last-failure timestamps and current state (ok / degraded / disabled-until), via `GET /api/v1/system/health` for the UI. A single health-aggregation service SHALL compute the component list from already-persisted or cheap-live state (the per-provider back-off table, filesystem free-space and writability, database integrity and last-backup age, scheduler status) and derive BOTH this per-component view and the FRG-API-014 `/api/v1/health` warnings list from it — the checks owned by other areas are read, not re-implemented. A component that recovers SHALL clear on the next poll without a restart.

- **Milestone**: M2
- **Source**: mylar-comicvine.md §1.3 (BACKENDSTATUS_CV surfaced in UI); sonarr-architecture.md §2.6/§7.1 (indexer status, Health resource).
- **Notes**: Aggregates into DEP's root `/health` liveness (container-level up/down) but is the richer per-provider view. Reuses `providers/backoff.py::ProviderBackoff.health()` (level / disabled-until / last-failure — FRG-NFR-005/IDX-010) for the provider components, root-folder free-space (already surfaced on Media Management), and the FRG-DB-012 integrity result + FRG-DB-009 last-backup age for the `database` component — no new tracking table. Surfacing is poll-first (React Query refetch): low-frequency, and recovery clears on the next poll. A disk-space component warns below a documented low-space floor.

#### Scenario: An indexer in back-off shows degraded with its disabled-until time

- **WHEN** an indexer is forced into failure back-off and `GET /api/v1/system/health` is requested
- **THEN** that indexer component reports `degraded`/`disabled-until` with its disabled-until timestamp and last-failure time, and after the back-off recovers a subsequent poll shows it `ok` again with no restart

#### Scenario: Every tracked component is represented with state and timestamps

- **WHEN** `GET /api/v1/system/health` is requested
- **THEN** ComicVine, each configured indexer, each download client, the DDL provider, the scheduler, the database, each root folder, and disk space each appear with a state (ok / degraded / disabled-until) and last-success/last-failure timestamps where applicable

#### Scenario: The warnings list and the per-component view derive from one service

- **WHEN** the same underlying state produces both `GET /api/v1/health` and `GET /api/v1/system/health`
- **THEN** the two never disagree — the warnings list is exactly the non-ok subset of the per-component view (each warning carrying a remediation hint), computed by the single aggregation service rather than a parallel check path

#### Scenario: Database health reflects integrity and last backup

- **WHEN** the database component is inspected after a failed integrity check or with a stale/absent last scheduled backup
- **THEN** the `database` component reports the corresponding error/warning (integrity failure named; a missing or overdue backup surfaced) and returns to `ok` once integrity passes and a recent backup exists
