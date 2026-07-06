# Design: m2-settings-naming-config

## Context

M2 change 1 of 6. M1 (archived `2026-07-06-m1-import-pipeline`) built the whole naming
+ file-op machinery but exposed none of it: `renamer.py` renames every import with the
fixed `DEFAULT_FILE_TEMPLATE`, `fileops.quarantine_file` parks upgrade-replaced files
under `<config>/quarantine/<date>/` as an explicit recycle-bin stand-in (design
decision 8 + FRG-PP-010 scenario 3), and `config.py` writes an unversioned `config.yaml`.
This change hands the operator the controls: naming/media-management settings, a
preview→execute rename flow for existing library files, a first-class recycle bin
(re-homed here from the dissolved quality change per the owner's 2026-07-06 decision),
the config resource endpoints the settings screens read/write, and versioned config-file
migration mirroring the DB's `db/migrations.py` backup discipline. Sonarr's
media-management screen (`docs/research/sonarr-ui/` §10) is the settings-screen blueprint;
its RenameEpisodeFileService preview/execute split is the PP-012 blueprint.

## Goals / Non-Goals

**Goals:** operator-editable global naming templates + media-management toggles feeding
the change-6 pipeline seams; a pure preview of existing→new library paths that touches no
disk, executed as an explicit second step reusing `place_file`; a configured recycle bin
replacing the quarantine stand-in for upgrade-replaced files and user deletions (never
hard-delete when a bin is set), with retention pruning and clean migration of the existing
quarantine dir; typed GET/PUT config resources; a `config_schema_version` stamp with
forward stepped migration, pre-migration backup, and refuse-newer.

**Non-Goals:** manual import (change 2), existing-library import staging (change 3),
history/wanted screens (change 4), quality-profile scoring/size, per-series template
overrides (global only), ComicInfo.xml settings (change 2). The existing-library import
path itself is change 3 — this change only *defines* its config field.

## Decisions

1. **Preview is a pure function over rows + templates, no disk** (FRG-PP-012,
   `importer/rename_ops.py` new): `preview_renames(series, issue_files, ctx) ->
   RenamePlan` where each entry is `(issue_file_id, current_path, new_path, changed)`.
   It reuses the exact import builders — `pipeline.build_fields(series, issue, evidence)`
   → `renamer.render_filename(fields, template=ctx.file_template, ext=…,
   enabled=ctx.rename_enabled)` → `security.paths.safe_join(series.path, new_name)` — so a
   preview can never propose a name the import path would not. It reads `issue_files` rows
   and never calls `os` mutators; `changed` is `new_path != current_path`, and unchanged
   entries are excluded from execution. This is the *library re-organization* path, distinct
   from the initial import path (`pipeline.execute`), which names files directly at import
   time. Same builder code, two entry points (decision 3 boundary).

2. **Execute re-derives the plan and reuses `place_file`** (FRG-PP-012): the execute step
   recomputes the plan from the same `issue_files` rows + current `ctx` and applies exactly
   the `current_path → new_path` moves via `fileops.place_file(..., mode=MOVE)` (a
   same-directory rename is an atomic `os.replace`), updates `issue_files.path`, and writes
   one `history.EVENT_FILE_RENAMED` row per renamed file **inside the caller's
   write_session** (the FRG-PP-011 discipline). Recomputing rather than trusting a
   client-submitted plan keeps preview and execute byte-identical and closes the
   TOCTOU/tamper gap; no-op entries are skipped so execution is idempotent. The round-trip
   contract (FRG-PP-009) already holds for every name `render_filename` emits, so no renamed
   library file loses its `[__{IssueId}__]` identity.

3. **Import move/rename vs in-place — honest boundary.** M1 imports *do* move+rename: the
   DOWNLOAD path pulls a completed file out of a staging/download dir into the library, so
   `pipeline.execute` calls `place_file(mode=ctx.transfer_mode=MOVE)` +
   `render_filename(enabled=ctx.rename_enabled)`. Those `ImportContext` seams
   (`transfer_mode`, `rename_enabled`, `file_template`, `folder_template`) already exist —
   this change only surfaces them as media-management config feeding the flows command that
   builds the context. The DOWNLOAD path therefore keeps move+rename defaults (that is the
   only correct behavior for a file arriving in a download dir). "In-place, the safe
   default" applies to the *existing-library* import path (change 3): those files are already
   under the library root and must not be re-moved. We define one config field
   `library_import_mode: in_place | move` (default `in_place`) here; its consumer is wired in
   change 3. Stated crisply: **download import = move+rename (configurable transfer mode /
   rename toggle); existing-library import = in-place by default (field defined here, honored
   in change 3).**

4. **Recycle bin replaces `quarantine_file`** (FRG-PP-013, `fileops.py`):
   `quarantine_file(src, config_dir)` becomes `recycle_file(src, recycle_root,
   retention=…, now=…)`, keeping the collision-safe numeric-suffix naming and cross-device
   copy-verify-delete fallback already in `quarantine_file`. `pipeline.execute` swaps its
   `quarantine_file(ev.existing_file_path, ctx.config_dir)` call for `recycle_file` behind
   the same seam. Two new `ImportContext`/config values: `recycle_bin_path` (str, `""` =
   permanently delete on replacement) and `recycle_bin_retention_days` (int, `0` = keep
   forever). With no bin configured the superseded file is permanently deleted and the
   `EVENT_UPGRADE_REPLACED` event still records the replacement (`recycle_path=None`).

5. **Recycle destination is confinement-checked** (FRG-PP-013 + FRG-SEC-004): the bin is an
   operator-configured path, so `recycle_file` builds its destination via `safe_join` under
   the resolved `recycle_bin_path` root — the same rule as every other destination path in
   the pipeline. A configured path that fails the writable/confinement check is a config
   validation error (decision 8), not a silent fallback to permanent delete.

6. **User-initiated deletion routes through the bin too** (FRG-PP-013): deleting a library
   file through the app moves it to the recycle bin (never hard-delete when a bin is set) and
   writes `history.EVENT_FILE_DELETED` carrying the recycle path — the same `recycle_file`
   seam as the upgrade path, so there is one deletion policy, not two.

7. **Quarantine migration, no orphans** (FRG-PP-013): a one-shot startup/housekeeping step
   sweeps any pre-existing `<config>/quarantine/<date>/` files (M1's stand-in) into the
   configured recycle bin via `recycle_file`, recording the move on a history event; if no
   bin is configured the quarantine dir is left in place (retired, not deleted) so nothing is
   lost. Retention pruning is a housekeeping command that permanently removes bin entries
   older than `recycle_bin_retention_days` (mirrors the existing `job_history` /
   `db_backup_retention` prune pattern); `0` disables pruning.

8. **Config gains typed naming/media-management fields** (`config.py` `Settings`):
   `rename_enabled`, `file_naming_template`, `folder_naming_template`,
   `replace_illegal_characters`, `import_transfer_mode` (move|copy|hardlink),
   `library_import_mode` (in_place|move), `recycle_bin_path`, `recycle_bin_retention_days`.
   Each is a `Field` with description (so `generate_default_config` documents it) and a
   `field_validator`: templates are non-empty and must render+round-trip a probe identity;
   `recycle_bin_path` (when non-empty) must be a writable, confinement-safe directory — same
   fail-fast one-pass `ConfigError` path already in `load_settings`.

9. **Config schema version + forward migration** (FRG-DEP-004, `config_migrations.py` new,
   modeled on `db/migrations.py`): add `config_schema_version: int` (stamped into every
   written `config.yaml`, present from the first generated file). `load_settings` reads the
   file's stamped version and, before validating, runs a stepped migration registry
   (`{from_version: migrator}`, applied one step at a time) forward to the current version.
   Before rewriting, it backs the original up to `backups/pre-config-migration-<ver>-<ts>/`
   with retention pruning — reusing the *shape* of `db.migrations.backup_before_migration` /
   `prune_backups` (a new `config_backup_retention`, default 3). A file stamped *newer* than
   the build supports refuses startup with a field-precise error, config left untouched —
   the exact `SchemaVersionError` posture of `db/migrations.py` `_pending_revisions`.
   Unknown-but-valid keys already survive (`load_settings` warns-and-drops only keys not in
   `model_fields`; migrators preserve renamed/moved values explicitly).

10. **Config resource endpoints** (FRG-API-013, `api/config_resources.py` new): typed
    `GET`/`PUT` singletons `config/naming` and `config/mediamanagement` (host/ui deferred to
    their own reqs). Pydantic resource models over the relevant `Settings` fields; `PUT`
    validates and persists back into `config.yaml`, re-loading `app.state.settings`.
    Field-precise 4xx flows through the existing uniform shape (`api/errors.py` `ApiError` /
    `error_body`) with `errors[].field` naming the offending setting under a `settings.`
    prefix — the shape `frontend` `mapApiError` already strips. No secret-typed field appears
    in these resources (secrets remain DEP/AUTH surface); plain arrays vs paging is moot —
    these are singletons, like `library_config.py`'s read-only collections but mutable.

11. **UI reuses `SchemaForm`, adds two bespoke panels** (FRG-UI-012): the provider machinery
    (`ProviderSettingsPage` + `ProviderModal`) is a list+modal over *many* provider
    instances — wrong shape for a singleton settings page. So the media-management screen is a
    bespoke single-form page (Sonarr save-bar model, §10), but it *reuses the field renderer*
    `components/schemaForm/SchemaForm` for the standard fields (rename on/off, illegal-char
    policy, transfer mode, import mode, recycle bin path + retention). Two things the schema
    renderer cannot express get bespoke components: (a) the **live example preview** under
    each template input, recomputing as the user types from one shared token vocabulary
    (sourced from `renamer._TOKEN_ALIASES`, exported for help + preview), and (b) the
    **per-series rename-preview table** (old→new diff list, apply-only-on-confirm) backed by
    the PP-012 preview/execute endpoints. Field errors reuse the `settings.`-prefix
    `mapApiError` path already in `ProviderModal`.

## Risks / Trade-offs

- **[Recycle bin on a different volume]** → `recycle_file` inherits `quarantine_file`'s
  cross-device copy-verify-delete fallback, so a bin on another mount still never deletes
  before the copy is verified; documented as accepted latency on upgrade.
- **[Quarantine migration double-run]** → migration is idempotent (collision-safe naming; a
  moved file is gone from quarantine), and a history event marks completion — re-running the
  sweep finds nothing to move.
- **[Preview drift vs execute]** → mitigated by execute *recomputing* the plan (decision 2)
  rather than trusting the client; a file changed on disk between preview and execute is a
  no-op or re-planned, never a blind move.
- **[Config migrator bug corrupts config]** → the pre-migration backup (decision 9) is the
  recovery path, exactly as the DB story; refuse-newer prevents an older build from
  down-migrating a file it does not understand.

## Migration Plan

No DB migration. Additive config fields with safe defaults (bin off ⇒ permanent-delete,
identical to M1's delete-nothing-but-quarantine behavior only where a bin is set;
in-place default for the not-yet-wired library import). `config_schema_version` is stamped
into existing configs on first migrated write, with a retained backup. Quarantine→recycle
sweep runs once and is idempotent. Rollback = don't merge (a newer config file then refuses
an older build, by design).

## Open Questions

None blocking.
