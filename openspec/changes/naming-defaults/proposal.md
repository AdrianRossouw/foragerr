# naming-defaults

## Why

The first real dogfooding session (2026-07-12) exposed that foragerr's shipped defaults are destructive: adopting an existing library renamed 527 files uninvited, stamping every one with a `[__{IssueId}__]` tag that embeds *internal database row ids* — identifiers that become meaningless (and, worse, silently mis-mappable) after any database reset or reinstall, which is exactly the clean-slate path planned for 1.0. Mylar and Sonarr both treat adoption as non-destructive; users migrating from them expect the same.

## What Changes

- **`rename_enabled` defaults to `false`** (was `true`): a fresh install adopts an existing library byte-for-byte and name-for-name; downloads still move into the library but keep their release names until the operator opts into renaming. Existing installs keep their current effective behavior (persisted config wins; only fresh installs see the new default).
- **Default `file_naming_template` drops the identity tag**: `{Series Title} {Issue Number:000} ({Year})` (was `... [__{IssueId}__]`). The round-trip validation (every template must render names that re-parse to the same issue) stays mandatory and is unaffected — the tag was never required for it.
- **New `{CvIssueId}` token** as the durable opt-in identity tag: ComicVine issue ids survive reinstalls and database resets; internal row ids do not. `{IssueId}` remains supported for compatibility but is no longer in any default.
- **Stale-tag hazard closed**: the import pipeline currently treats a parsed `[__id__]` tag as authoritative on unscoped imports (`_BASE_TAG` short-circuit), with the disagree-fall-through guard applied only to scoped rescans. After a reinstall, stale tags point at arbitrary rows and can silently attach files to the wrong issue. The guard becomes universal: a tag whose target disagrees with the filename parse falls through to the filename heuristic on **every** import.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `pp`: FRG-PP-009 (token engine — `{CvIssueId}` joins the minimum token set; default template pinned tag-free), FRG-PP-003 (issue-id tag short-circuit requires agreement with the filename parse or an in-scope series), and new FRG-PP-020 (non-destructive defaults: fresh installs rename nothing; persisted configs are never re-defaulted).

## Impact

- **Code**: `backend/src/foragerr/config.py` (defaults), `backend/src/foragerr/importer/pipeline.py` (base-resolution guard), naming token engine (`{CvIssueId}`), config save/load (no migration needed — persisted values already win over defaults; verified as part of tasks).
- **API**: none (config resource shapes unchanged; values only).
- **Dependencies / SOUP**: none.
- **Manual** (FRG-PROC-011): `docs/manual/user/import.md` (defaults, round-trip/tag wording, `{CvIssueId}`), `docs/manual/admin/configuration.md` (default values table).
- **Registry** (FRG-PROC-002): allocate FRG-PP-020.
- **Security**: no new attack surface (FRG-PROC-006 n/a).

## Approval

Approved — Adrian, 2026-07-13 (in-session, alongside cbr-support; both queued as the next development).
