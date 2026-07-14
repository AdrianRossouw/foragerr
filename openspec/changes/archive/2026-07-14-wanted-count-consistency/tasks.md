# Tasks: wanted-count-consistency

## 1. Backend — single definition of "missing" (FRG-SER-009)

- [ ] 1.1 In `backend/src/foragerr/library/repo.py`, factor the wanted predicate
  (series monitored AND issue monitored AND released AND no issue_file) so
  `wanted_issues()` and `series_statistics()` share ONE definition — a common
  released/monitored/no-file condition (helper or count over the `wanted_issues()`
  selectable filtered to the series), not duplicated SQL.
- [ ] 1.2 Rewrite `series_statistics().missing_count` to that predicate (drop the
  `issue_count - file_count` shortcut); keep `have`/`total` as raw counts and keep
  `missing_count` derived-at-request-time (no stored column). Thread the existing
  `as_of` so "released" uses the same clock as `wanted_issues()`.
- [ ] 1.3 Tagged test `FRG-SER-009`: a series with released-monitored-fileless,
  unreleased-monitored-fileless, unmonitored-released-fileless, and has-file issues
  → `missing_count` counts only the released monitored fileless ones, is NOT
  `issue_count - file_count`, and equals `len(wanted_issues())` filtered to that
  series. Assert the single-definition invariant explicitly.
- [ ] 1.4 Check consumers of `missing_count` (series list/detail resources, the
  comics-grid "with missing" rollup) still behave; adjust any test fixtures that
  assumed the old `issue_count - file_count` value.

## 2. Frontend — drop the misleading nav count badges (FRG-UI-023, FRG-UI-029)

- [ ] 2.1 `frontend/src/components/Sidebar.tsx`: remove the `wanted` and `series`
  (Comics library-size) badge kinds; the Wanted and Comics nav items render icon +
  label only. Keep ONLY the Activity/Queue (queue length) active-work badge.
- [ ] 2.2 `SourcesNavBadge`: keep the amber `!` expired path, remove the
  `useSourcesNewCount` count path (and drop the now-unused hook / query key if
  nothing else uses it).
- [ ] 2.3 Update `Sidebar.test.tsx`: assert the Comics and Wanted nav items have no
  count badge even with series/missing issues present (`nav-badge-series` and
  `nav-badge-wanted` absent); assert the Sources badge shows `!` on expiry and
  nothing when only unreviewed-new exist; the Queue badge still renders. Tag with
  FRG-UI-023 / FRG-UI-029.

## 3. Docs

- [ ] 3.1 `docs/manual/`: if the Wanted or Sources sections mention the nav count
  badges, update them (Wanted count lives on its page; Sources nav shows only the
  expiry indicator). If not mentioned, record "none" with rationale in the change.
- [ ] 3.2 CHANGELOG entry (Fixed: missing-count over-count on unreleased/unmonitored
  issues; Changed: dropped the Wanted and Sources nav count badges) + version bump
  via the `/release` skill, in this change branch.

## 4. Gate

- [ ] 4.1 Full frontend + backend suites green; regenerate the matrix; flip the
  modified requirements' rows if needed; `soup_check.py`, `risk_register_check.py`,
  `trace.py` exit 0.
- [ ] 4.2 Review gate (tiered — small, no new attack surface: targeted angles +
  Codex). The `missing_count` predicate refactor gets the adversarial angle
  (does the count still equal the list across the fixture matrix?).
- [ ] 4.3 Optional after merge: re-run the screenshot refresh so the shots drop the
  removed badges (or note it rides the next refresh).
