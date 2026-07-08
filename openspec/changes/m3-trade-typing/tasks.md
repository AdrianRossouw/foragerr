Work areas by file ownership (FRG-PROC-008). A (backend) lands first; B (frontend)
codes against A's `booktype` field; C closes the gate. Every requirement gets a tagged
test (FRG-PROC-004).

## A. Backend — collected-edition typing + the non-suppression invariant (FRG-SER-018, FRG-SER-019)

*Subtlety: HIGH — the non-suppression of wanted is the correctness core.* Owns:
`library/models.py`, migration `0014`, new `library/booktype.py`, `library/flows/add.py`
+ `refresh.py` + `edit_delete.py`, `api/series.py`.

- [x] A.1 `SeriesRow.booktype` (nullable Text) + `booktype_locked` (bool default false);
      migration `0014_series_booktype` (down_revision `0013_series_groups`, forward-only).
      Passes `test_repo_hygiene`. Migration test. [FRG-SER-018]
- [x] A.2 `library/booktype.py::detect_series_booktype(title)` reusing `parser.vocab`
      `BOOKTYPE_CUES`/`booktype_cue_phrases` (longest-first), returning `tpb`/`gn`/`hc`/
      `one_shot`/None. Unit tests over real title shapes (TPB/GN/HC cue → typed; no cue
      → None; cue-in-word safety). [FRG-SER-018]
- [x] A.3 Auto-derive at add + refresh when NOT `booktype_locked`; operator override via
      the edit flow (set book-type → lock; clear lock → re-derive next refresh), reusing
      the group/aliases-override validated sub-object precedent. Tagged tests: cue title
      auto-typed, no-cue null; override persists across refresh; clearing the lock
      re-derives. [FRG-SER-018]
- [x] A.4 **Non-suppression invariant (the core)** — do NOT touch `wanted_issues`/
      `series_statistics`. Tagged tests: (a) a single-issues series with missing wanted
      issues + a fully-owned collected series of the same title → every single issue
      stays wanted (`wanted_issue_ids`); (b) typing a series → `wanted_issues`/
      `series_statistics` byte-identical before/after; (c) the pull matcher book-type
      guard still matches a typed line's entries. [FRG-SER-019]
- [x] A.5 `booktype` on `SeriesResource` (via `_series_fields`); accepted on `SeriesEdit`
      (validated); optional `collected` filter on `GET /series` (booktype IS/IS NOT
      NULL). Tagged tests: resource carries booktype; edit sets+locks; filter partitions;
      no secret. [FRG-SER-018]

## B. Frontend — collected-edition surfacing (FRG-UI-022)

*Subtlety: MEDIUM.* Owns: `frontend/src/screens/library/`, `screens/series/`,
`api/types.ts`, `store/uiStore.ts`. Depends on A's `booktype` field.

- [x] B.1 `SeriesResource` type gains `booktype`; a small book-type badge (TPB/GN/HC) on
      `PosterCard` (library, incl. inside a franchise group) and the `SeriesDetail` hero;
      null → no badge. Vitest (FRG-UI-022): typed series shows the badge, null shows none.
      [FRG-UI-022]
- [x] B.2 A library filter toggle (all / collected / single-issues) in the toolbar/view
      state; display-only. Vitest: filter partitions the shown series; per-series actions
      unchanged. [FRG-UI-022]

## C. Docs, traceability, gate

- [x] C.1 Manual (FRG-PROC-011): `docs/manual/user/library.md` documents collected-edition
      typing, the badge/filter, and prominently that owning a trade never affects
      single-issue wanted state. No security/SOUP change. [FRG-PROC-011]
- [x] C.2 Registry + matrix: FRG-SER-018/019, FRG-UI-022 flip `proposed → implemented`;
      matrix regenerated; `tools/trace.py` exit 0. [FRG-PROC-004, FRG-PROC-005]
- [x] C.3 Gate: backend + frontend suites green; pre-merge review cycle (8 Claude angles
      + Codex, with the non-suppression invariant a named angle); fixes; archive;
      `--no-ff` merge; CHANGELOG v0.3.3 + `pyproject` bump + tag v0.3.3 + GitHub Release
      per FRG-PROC-013. This completes the M3 backend/typing cluster (change 2, the pull
      screen, remains parked for the design review). [FRG-PROC-007, FRG-PROC-013]
