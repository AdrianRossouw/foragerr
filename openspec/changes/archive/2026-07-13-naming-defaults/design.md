# naming-defaults — design

## Context

Three shipped behaviors interact badly for a migrating user:

1. `rename_enabled` defaults `true` (config.py), so `library-import execute` renames every adopted file to the default template.
2. The default template ends in `[__{IssueId}__]` — the **internal issue row id**. Row ids are assigned in insertion order per database; they do not survive a reinstall, restore-from-scratch, or the planned 1.0 clean slate.
3. `importer/pipeline.py` base resolution (`_resolve_base`, FRG-PP-003) short-circuits on a parsed `issue_id` tag: `session.get(IssueRow, iid)` and, when the row exists, returns it as `_BASE_TAG` — *authoritative above the embedded-metadata layer*. The disagree-fall-through guard (tag's series must match) applies **only when `candidate.series_scope_id` is set** (scoped rescans). On unscoped imports a stale tag from a previous install maps to whatever row now holds that id. The 2026-07-12 demo only imported correctly by creation-order luck.

## Goals / Non-Goals

**Goals:**
- Fresh installs never modify adopted files (Sonarr/Mylar parity).
- No internal row ids in any default-rendered filename; durable `{CvIssueId}` available for operators who want identity tags.
- A parsed identity tag can never override a *disagreeing* filename parse.
- Existing installs observe zero behavior change without operator action.

**Non-Goals:**
- Un-renaming files already stamped by the old default (operator's files; a rename-preview pass can do this manually via FRG-PP-012).
- Changing folder templates, move semantics, or `library_import_mode`.
- Removing the `{IssueId}` token (kept for round-trip compatibility with already-stamped libraries).

## Decisions

1. **Defaults change only at the source** — `config.py` field defaults (`rename_enabled=False`, new `DEFAULT_FILE_TEMPLATE`). Persisted config files already shadow defaults on load, so existing installs keep behaving as configured with no migration machinery. A startup config-migration is explicitly *not* needed; a task verifies this with a test loading a v0.9.1-shaped config file.
2. **`{CvIssueId}` token** renders `issues.cv_issue_id`; parser gains the matching recognition (a `[__cv<ID>__]`-distinct form is NOT introduced — the token renders bare inside the existing `[__…__]` bracket vocabulary? **No**: to keep old and new tags distinguishable, `{CvIssueId}` renders as `[cvid-<ID>]` and the parser recognizes that form into the existing `cv_issue_id` evidence namespace, which the pipeline already consults (`pipeline.py` embedded-layer lookup by `IssueRow.cv_issue_id`). No new resolution path — the tag feeds the *existing* cv-id namespace.)
3. **Universal disagree-guard**: `_resolve_base` keeps the tag short-circuit but adds the same fall-through used for scoped rescans, generalized: when the tag's resolved issue disagrees with the filename parse (different series matching key, or filename parses to an issue number the tagged issue doesn't carry), fall through to grab-history/filename heuristics. Tag-only files (unparseable names) still resolve by tag — that's the tag's legitimate job (FRG-PP-003 DDL convention).
4. **Round-trip stays load-bearing**: template validation at startup/save is untouched; the new default template must pass the same corpus property tests (it already does — it's the old template minus the tag).

## Risks / Trade-offs

- **Downloads keep scene names by default** — the trade for non-destructive adoption; operators who want clean names flip one switch (and now get a sane template). Documented in the manual.
- **Tag-only DDL names**: the guard must not regress FRG-PP-003's unparseable-name scenario — covered by keeping tag-resolution when the filename parse yields nothing to disagree with.
- **Already-stamped libraries** (including the owner's sample library): old `[__id__]` tags stay in filenames until the operator renames; with the universal guard they are harmless (filename parse wins on disagreement).
