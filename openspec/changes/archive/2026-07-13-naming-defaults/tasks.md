# naming-defaults — tasks

## 1. Registry and config defaults

- [x] 1.1 Allocate FRG-PP-020 in docs/traceability/requirements-registry.md (status: approved on owner sign-off)
- [x] 1.2 Flip `rename_enabled` default to `False` and set `DEFAULT_FILE_TEMPLATE = "{Series Title} {Issue Number:000} ({Year})"` in backend/src/foragerr/config.py; keep template round-trip validation untouched
- [x] 1.3 Test (FRG-PP-020): fresh-settings instance renames nothing on an in_place library import — file paths byte-identical before/after
- [x] 1.4 Test (FRG-PP-020): a persisted config file shaped like a v0.9.1 install (`rename_enabled: true`, old tagged template) loads with its values intact — persisted beats default

## 2. {CvIssueId} token

- [x] 2.1 Add `{CvIssueId}` to the naming token engine rendering `issues.cv_issue_id` as `[cvid-<ID>]`; empty when the issue has no CV id (optional-group semantics apply)
- [x] 2.2 Teach the IMP parser to recognize `[cvid-<ID>]` into the existing cv-issue-id evidence namespace (no new resolution path)
- [x] 2.3 Test (FRG-PP-009): render-with-CvIssueId → re-parse → resolves to the same issue on a second database with different internal row ids (reinstall simulation)
- [x] 2.4 Extend the round-trip corpus property tests to templates containing {CvIssueId}

## 3. Universal stale-tag guard

- [x] 3.1 Generalize the `_resolve_base` disagree-fall-through in backend/src/foragerr/importer/pipeline.py: tag resolution is discarded whenever the tagged issue disagrees with the filename parse (series matching key or contradicted issue identity), on scoped AND unscoped imports
- [x] 3.2 Test (FRG-PP-003): stale tag pointing at a different series' row + parseable filename → file resolves via filename heuristic, not the tag
- [x] 3.3 Test (FRG-PP-003): tag-only unparseable name still resolves by tag (DDL convention non-regression)
- [x] 3.4 Test (FRG-PP-003): tag agreeing with the filename parse still short-circuits (fast-path non-regression)

## 4. Docs, gate, and merge

- [x] 4.1 Update docs/manual/user/import.md (new defaults, non-destructive adoption, {CvIssueId} as the durable tag, note on already-stamped libraries) and docs/manual/admin/configuration.md (defaults table)
- [ ] 4.2 Regenerate traceability matrix; tools/soup_check.py exit 0 (no dep changes)
- [ ] 4.3 Full suite green; tiered review gate per docs/process/commit-standard.md (small change: 2-3 angles + Codex); merge --no-ff; delete branch
