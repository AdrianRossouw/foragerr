# import-atomicity — design

## Context

`_import_group` (`library/flows/library_import.py`) runs, per group:
1. `add_series(...)` — creates + commits the series row (with
   `enqueue_refresh=False`; monitored flags set; a search may be enqueued
   via `search_on_add`).
2. `_refresh_before_import(...)` — fetches the issue list; returns False →
   group outcome `"refresh-failed"`, **series already committed**.
3. gather + `import_candidate(...)` — attaches files.

There is no transaction spanning 1–3 and no compensating delete, so a
failure at 2 (or a post-add exception → `"errored"`, or all files blocked
with a freshly-created series) leaves a committed, monitored, issueless
series. The scheduled metadata refresh (FRG-META-009) + monitoring +
backlog search then "complete" it independently of the operator's failed
import.

## Goals / Non-Goals

**Goal**: a group that creates a new series but attaches no file leaves no
series behind. **Non-goals**: the rest of the parked import-heuristics
pre-design; read-only roots; any change to successful/partial-with-files
imports.

## Decisions

**D1 — Compensating rollback of a group-created shell, tracked by "did
this group create it".** Simplest and lowest-blast-radius: `_import_group`
records whether it created the series in *this* run (the `else` branch at
line 862, vs. the reuse branch). If the group returns without attaching ≥1
file (`refresh-failed`, `errored`, or blocked-with-zero-imported on a
freshly created series), delete that series through the existing
series-delete path (files-on-disk untouched — the delete is metadata-only,
FRG-SER-008) and cancel/deduplicate any search it enqueued. A reused or
pre-existing series is never eligible. Rationale: keeps the create → refresh
→ attach sequence (each step's own transaction) but makes the *series*
contingent; avoids a large refactor of `add_series` into a deferred-commit
mode. Alternative — defer the series INSERT until after a successful attach
(build issues/files first, then create) — rejected for now: it inverts the
add flow the whole codebase depends on (path build, refresh, monitoring
all key off an existing series id) and is a much larger change than the
compensating delete.

**D2 — The add-enqueued search must not outlive the rollback.** With
`enqueue_refresh=False` the add path does not self-refresh, but
`search_on_add` may enqueue a search command. The rollback SHALL cancel or
no-op that search (the series id it targets is gone), so a rolled-back
group triggers no grab. Where a search command cannot be un-queued, its
handler already no-ops on a missing series — verify and rely on that,
else guard.

**D3 — Reason reporting unchanged.** `_set_group_outcome` still records
the honest failure reason on the staging row before the rollback, and the
post-run WARNING per failed group is unchanged (FRG-IMP-023). The rollback
is silent to the operator beyond "it failed, and nothing was half-added."

## Risks / Trade-offs

- [Deleting a series a concurrent action just started using] → the rollback
  is scoped to a series THIS group created in THIS run and only when it
  attached zero files; the delete path already guards referencing series.
  A same-run race is bounded by per-group sequential processing.
- [A genuinely-partial import (some files attached, some blocked) must keep
  its series] → the "attached ≥1 file" test is the keep/rollback boundary;
  `imported > 0` keeps it.
- [Search side effect] → D2.

## Migration Plan

None — behavioral. Rollback = revert the change.

## Open Questions

Whether to additionally cover the "series created, files all *blocked*"
case as a rollback (no files attached) or leave the shell so the operator
can fix placement and re-run against the existing series. Leaning rollback
(consistent "no attach ⇒ no shell") with the re-run creating it cleanly —
confirm at implementation.
