# Change: m2-settings-naming-config — naming control, rename preview, recycle bin

## Why

M2 change 1 of 6 ("own your library", decomposition approved under the 2026-07-06
standing grant). M1 renames files with a fixed default template and quarantines
replaced files; the operator cannot see or change naming behavior, preview the
effect of a template change, or recover a deleted file through a first-class
recycle bin. This change gives the operator control of the machinery change 6
built: naming/media-management settings with a live rename preview, the
preview→execute rename flow for existing files, the recycle bin (re-homed here
from the dissolved quality change per the owner's 2026-07-06 decision), the
config resource endpoints the settings screens need, and versioned config-file
migration so settings evolve safely across upgrades.

## What Changes

Implements 5 approved baseline requirements (no new IDs; scenario elaboration
only):

- **FRG-PP-012 — Rename preview before execution.** Existing-path → new-path
  previews for any series/file selection under the current templates, computed
  without touching disk; execution is an explicit second step emitting per-file
  rename events, reusing the change-6 renamer + safe file ops (same builder as
  import naming; the round-trip contract keeps holding for every executed name).
- **FRG-PP-013 — Upgrades and deletions via recycle bin.** A configurable
  recycle-bin directory replaces M1's `<config>/quarantine/` stand-in for
  upgrade-replaced files AND becomes the destination for user-initiated file
  deletions (never hard-delete); retention pruning as a housekeeping task; the
  quarantine dir migrates/retires cleanly (recorded on history events either way).
- **FRG-UI-012 — Settings: media management and naming.** Sonarr-school settings
  screen: file/folder template editing with token help, live rename preview
  against a real series, recycle-bin + import-behavior toggles; schema-driven
  where the existing provider-settings renderer generalizes.
- **FRG-API-013 — Config resource endpoints.** Typed read/update endpoints for
  the naming/media-management config resources backing the screen (validation
  errors per field; secrets never involved here).
- **FRG-DEP-004 — Versioned config-file migration.** `config.yaml` gains a
  schema version; startup migrates older files forward (with the pre-migration
  backup discipline the DB already has) and refuses newer-than-supported files.

Owner-decided scope note (2026-07-06, `docs/process/decisions.md`): import stays
CONFIGURABLE here — move/rename-on-import vs import-in-place, in-place the safe
default — surfaced as media-management settings feeding the change-6 pipeline's
existing seams.

## Capabilities

### Modified Capabilities

- `pp`: FRG-PP-012, FRG-PP-013
- `ui`: FRG-UI-012
- `api`: FRG-API-013
- `dep`: FRG-DEP-004

## Non-goals

- No manual import (change 2), no existing-library import staging (change 3), no
  history/wanted screens (change 4).
- No quality-profile scoring/size settings (FRG-QUAL-003/004/005 parked to B).
- No per-series template overrides (global templates only in M2).
- No ComicInfo.xml settings (change 2 carries FRG-PP-017 alongside manual import).

## Impact

- **Code**: `backend/src/foragerr/importer/renamer.py` (preview seam),
  `fileops.py` (recycle bin), new `api/config_resources.py`; config schema
  version + migration in `config.py`; `frontend/src/screens/settings/` naming
  screen + preview components.
- **Security**: no new listener surface class (authenticated-surface posture
  unchanged; endpoints are same-origin API resources). Recycle-bin paths are
  operator-configured and confinement-checked like every destination path
  (`security.paths`). Risk register: RISK-019/029 unchanged dispositions apply;
  no new rows anticipated — verified at the gate per FRG-PROC-006.
- **Registry**: on merge, the 5 rows flip `approved → implemented`.

## Manual impact

`docs/manual/user/import.md` (rename preview + recycle bin replace the
quarantine stand-in; naming templates now user-visible),
`docs/manual/admin/configuration.md` (new naming/media-management settings,
config schema version + migration behavior). Declared per FRG-PROC-011.

## Approval

- **Approver:** Adrian
- **Date:** 2026-07-06
- **Decision:** Approved under the M2/M3 standing grant of 2026-07-06 ("keep
  going with m2/m3 and all their related changes as you go. I'll come check in
  later"), which covers the 6-change M2 decomposition this proposal implements
  change 1 of, including the PP-013 re-homing decision.
