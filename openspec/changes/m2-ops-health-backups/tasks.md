# Tasks — m2-ops-health-backups

Grouped into parallelizable work areas by file ownership. Backend core (area 1)
exposes the backup/health primitives; API wiring (area 2) owns `app.py` and the
routers that call them; frontend (area 3) owns `frontend/`; docs + security
(area 4) owns `docs/`. Every task cites its requirement IDs. Testing:
pytest `@pytest.mark.req("FRG-...")`; vitest tests include the ID in the name.

## 1. Backend db / backup + health core

- [ ] 1.1 Extract a shared `write_consistent_backup(db_path, dest_dir)` from
      `db/migrations.py` (checkpoint + `source.backup(destination)`); repoint
      the pre-migration path at it (no behavior change). Add
      `db/backup.py`: scheduled-backup writer to
      `/config/backups/scheduled-<timestamp>/` (DB via the shared primitive +
      config file via `shutil.copy2`) and a `scheduled-*`-scoped pruning helper.
      New config keys `db_backup_interval_seconds` (default 86400, documented
      minimum) and `db_scheduled_backup_retention` (`ge=1`, default 7). Tests:
      copy is consistent + passes `integrity_check`; retention prunes only
      `scheduled-*` and never `pre-migration-*`. [FRG-DB-009]
- [ ] 1.2 `BackupDatabaseCommand` (`exclusivity_group="backup"`) + handler:
      full `PRAGMA integrity_check` → checkpoint+backup → copy config → prune.
      A failed integrity check ABORTS (no dir written) and raises a `database`
      health error. Tests: happy path writes a dir + job-history row; corrupt DB
      aborts with no dir and a recorded health error. [FRG-DB-009, FRG-DB-012]
- [ ] 1.3 Startup `PRAGMA quick_check` hook: failure logs loudly and marks the
      `database` component error in the health surface (app still boots). Tests:
      corrupted DB boots but reports the database error; a clean DB reports ok.
      [FRG-DB-012]
- [ ] 1.4 Startup restore-marker hook (`/config/restore-from`): resolve target
      under `/config/backups` via `security.paths` confinement, verify the
      backup's `integrity_check`, snapshot live DB+config to
      `pre-restore-<timestamp>/`, swap in, delete marker — all before the engine
      opens. Tests: valid marker restores to the backup point; traversal/absolute
      target refused (live files untouched); corrupt backup refused; no marker =
      no-op. [FRG-DB-010]
- [ ] 1.5 Health-aggregation service (`health/service.py`): compute the
      per-component list from `ProviderBackoff.health()` (ComicVine / indexers /
      SAB / DDL), root-folder existence+writability+free-space, DB integrity +
      last-backup age, scheduler status, and a low-disk floor. Expose a derive
      helper for the warnings subset (with remediation hints) and the full
      per-component view. Tests: indexer back-off → degraded+disabled-until,
      recovery clears; every component represented; warnings = non-ok subset;
      database reflects integrity + last-backup age. [FRG-NFR-011]

## 2. API + scheduler wiring

- [ ] 2.1 Register the `backup-database` scheduled task in `app.py`
      (`scheduler.register_task`, interval from config, min-interval clamp) and
      import the command module so the command/handler register. Tests: task
      appears in `scheduler.status()`; tick enqueues on interval. [FRG-DB-009]
- [ ] 2.2 Extend `api/system.py` `system_status`: add runtime (uptime, python,
      OS) + managed paths (config dir, db path, backups dir, root-folder count);
      keep `{version, commit, build_date}` byte-for-byte; assert no secret is
      present. Tests: new fields present, existing fields unchanged, no secret
      leak. [FRG-API-014]
- [ ] 2.3 `GET /api/v1/health` (warnings list from the health service:
      `{source, type, message, remediationHint}`) — distinct from the root
      `/health` (leave DEP's probe untouched). Tests: failing indexer surfaces a
      warning item; healthy = empty/all-ok; root `/health` behavior unchanged.
      [FRG-API-014, FRG-NFR-011]
- [ ] 2.4 `GET /api/v1/system/health` (per-component view from the service).
      Tests: every component with state + timestamps; recovery reflected on
      re-request. [FRG-NFR-011]
- [ ] 2.5 `GET /api/v1/system/task` (enriched `scheduler.status()` with command
      name + label) and `POST /api/v1/system/task/{name}` (→ `force_run`, returns
      the command record; 404 on unknown task). Tests: list includes
      `backup-database`; force-run enqueues + returns command id + resets timer;
      unknown name 404. [FRG-API-014]

## 3. Frontend System area

- [ ] 3.1 System nav group + Status screen: version/build, managed paths,
      runtime table; no secret rendered. Vitest per delta scenario. [FRG-UI-016]
- [ ] 3.2 Health screen: warnings list with type icons + remediation hints, and
      the per-component table (ok / degraded-with-disabled-until countdown /
      error); explicit all-healthy state; poll refetch so recovery clears
      without manual refresh. Vitest. [FRG-UI-016, FRG-NFR-011]
- [ ] 3.3 Tasks screen: scheduled-task table (interval, last/next run) with
      per-task force-run buttons and a "Back up now" action on the backup task;
      reflect the returned command status to terminal; last/next-run update after
      run. Vitest. [FRG-UI-016]

## 4. Docs, security, traceability, gate

- [ ] 4.1 Security: add accepted-risk row **RISK-041** (plaintext provider
      credentials in DB/config backups — verbatim wording per the proposal;
      accept for M2–M4, compensating controls, M5/FRG-AUTH-008 deferral, review
      trigger) to `docs/security/risk-register.md`, and a threat-model delta in
      `docs/security/threat-model.md` for the backup artifact (info-disclosure)
      and the restore-marker hook (path confinement under `/config/backups`).
      [FRG-PROC-006]
- [ ] 4.2 Manual: `admin/configuration.md` (backup interval + retention +
      integrity settings; what a backup contains + the plaintext-credentials
      caveat pointing at RISK-041); `admin/deployment.md` (restore procedure —
      offline swap + `/config/restore-from` marker hook; where backups live under
      `/config`); `user/web-ui.md` (System area: Status / Health with remediation
      hints / Tasks with force-run + "Back up now"). [FRG-PROC-011]
- [ ] 4.3 Registry flips (FRG-DB-009, FRG-DB-010, FRG-DB-012, FRG-API-014,
      FRG-UI-016, FRG-NFR-011 → implemented) + matrix regen (`tools/trace.py`
      exit 0); `tools/soup_check.py` exit 0 (no SOUP change expected — if a
      dependency is added, update `docs/security/soup-register.md` in this
      change). [FRG-PROC-004, FRG-PROC-005, FRG-PROC-012]
- [ ] 4.4 Suites green (backend + frontend); the review gate (8-angle + Codex);
      fixes; `--no-ff` merge; main suites green; tag the release per FRG-PROC-013.
      [FRG-PROC-007]
