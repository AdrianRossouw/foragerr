Work areas by file ownership (FRG-PROC-008). A (all backend) lands first; B
(frontend) codes against A's endpoint; C closes the gate. Every requirement gets a
tagged test (FRG-PROC-004): pytest `@pytest.mark.req("FRG-SER-016")` / vitest with the
id in the test name.

## A. Backend — grouping model, derivation, override, projection (FRG-SER-016/017, FRG-API-020)

*Subtlety: HIGH — the non-regression of wanted/stats is the correctness core.* Owns:
`library/models.py`, migration `0013`, new `library/grouping.py`, `library/flows/add.py`
+ `refresh.py`, `library/repo.py`, `api/series.py`.

- [x] A.1 `series_groups` table (id, title, grouping_key UNIQUE, manual_title bool,
      created_at) + `SeriesRow.series_group_id` (nullable FK, ON DELETE SET NULL) +
      `SeriesRow.group_locked` (bool default false); migration `0013_series_groups`
      (down_revision `0012_issue_file_page_count`, forward-only). Must pass
      `test_repo_hygiene` (no `wanted` column; CHECKs intact). Migration test.
      [FRG-SER-016]
- [x] A.2 `library/grouping.py::franchise_key(title)` — strip a trailing `(YYYY)` and
      `Vol N`/`Volume N`, then `parser.normalize.matching_key`; empty → None. Unit
      tests over real title shapes (Batman runs fold; distinct titles don't; edge/empty).
      [FRG-SER-016]
- [x] A.3 Auto-group at add + refresh: find-or-create the group for `franchise_key` and
      link the series when NOT `group_locked`; new group title defaults to the stripped
      display title. Tagged tests: two runs of a title share one group; refresh keeps
      grouping; an empty-key series stays ungrouped. [FRG-SER-016]
- [x] A.4 Override (edit flow, `aliases`-precedent): reassign (set group + lock),
      detach (null group + lock), rename group (title + manual_title), clear-lock →
      re-derive; prune an emptied group. Tagged tests: reassigned series survives
      refresh (locked, not re-derived); rename persists across refresh; clearing the
      lock re-derives. [FRG-SER-017]
- [x] A.5 **Non-regression proof**: a test asserting `wanted_issues()` and
      `series_statistics` output is byte-identical before and after a series is grouped
      (no group/type predicate reached the choke point). [FRG-SER-016]
- [x] A.6 `GET /api/v1/series/groups` — a SINGLE aggregate query (join groups←series←
      issues/files, GROUP BY group) for series/total/owned counts (NO per-series stats
      N+1); ungrouped series returned as singleton franchises; standard paging envelope;
      no secret. `SeriesResource` gains nullable `series_group_id`. Tagged tests:
      grouped projection returns franchises + aggregated stats; flat list carries
      `series_group_id`; aggregation is one query (bounded). [FRG-API-020]

## B. Frontend — grouped library view (FRG-UI-021)

*Subtlety: MEDIUM.* Owns: `frontend/src/screens/library/`, `api/hooks.ts`,
`api/types.ts`, `store/uiStore.ts`. Depends on A's `GET /series/groups` contract.

- [x] B.1 `useSeriesGroups()` hook over `GET /series/groups`; `SeriesResource` type gains
      `series_group_id`. [FRG-UI-021]
- [x] B.2 Grouped display mode on the Comics screen (an orthogonal "group by franchise"
      toggle over the current mode): franchise headers (title + roll-up stat) with
      nested collapsible runs reusing the existing card/row rendering; single-run
      franchise renders as an ordinary row; per-series actions/nav unchanged. View
      state in `useUiStore`. Vitest: grouped mode nests runs under headers; toggling
      back shows the flat list unchanged. [FRG-UI-021]
- [x] B.3 Rename/reassign affordance reachable from a group header (calls the edit
      flow); vitest for the interaction. [FRG-UI-021, FRG-SER-017]

## C. Docs, traceability, gate

- [x] C.1 Manual (FRG-PROC-011): `docs/manual/user/` library/browsing section documents
      the grouped view + correcting a group; README labelling if it enumerates views.
      No security/SOUP change. [FRG-PROC-011]
- [x] C.2 Registry + matrix: FRG-SER-016/017, FRG-API-020, FRG-UI-021 flip
      `proposed → implemented`; matrix regenerated; `tools/trace.py` exit 0.
      [FRG-PROC-004, FRG-PROC-005]
- [x] C.3 Gate: backend + frontend suites green; pre-merge review cycle (8 Claude angles
      + Codex); fixes; archive; `--no-ff` merge; CHANGELOG v0.3.2 + `pyproject` bump +
      tag v0.3.2 + GitHub Release per FRG-PROC-013. [FRG-PROC-007, FRG-PROC-013]
