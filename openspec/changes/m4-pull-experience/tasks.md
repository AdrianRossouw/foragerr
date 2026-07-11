# Tasks — m4-pull-experience

## 1. Backend: future-week fetch window

- [x] 1.1 Extend `pull/commands.py::_fetch_weeks()` to `[previous, current,
      next]`; ensure an empty future-week payload is a logged skip, not an
      outage (FRG-PULL-009)
- [x] 1.2 Tagged pytest coverage in `backend/tests/pull/test_pull_commands.py`:
      next-week entries stored idempotently when provided; 619/empty future
      week skips only that week while previous/current store normally
      (`@pytest.mark.req("FRG-PULL-009")`)
- [x] 1.3 Projection/API regression: `GET /api/v1/pull?week=<next>` returns
      stored future entries merged with library-primary rows; existing
      FRG-PULL-001..006 / FRG-API-019 suites stay green (FRG-PULL-009)

## 2. Frontend: data layer

- [x] 2.1 `utils/isoWeek.ts` (currentIsoWeek / addWeeks / weekRangeLabel /
      weekDates) with year-boundary unit tests (FRG-UI-018)
- [x] 2.2 `queryKeys.pull` family + `useWeeklyPull(week)` hook with page
      aggregation past 200 rows; pull types in `api/types.ts` mirroring
      `PullEntryResource` (FRG-UI-018)
- [x] 2.3 `WebSocketBridge` invalidation: add `queryKeys.pull.all()` to the
      issue/queue/series event cases and pull-refresh command completion
      (FRG-UI-018, FRG-PULL-007)

## 3. Frontend: Calendar screen

- [x] 3.1 `screens/calendar/CalendarScreen.tsx` + module.css: toolbar (week
      nav, range label, publisher select, Following/All segmented), info
      banner, date-grouped agenda with day gutters, accent bars, release
      cards (publisher tint/accent spine, state icon), New Comic Day + Today
      badges, hidden/followed count notes, empty state, not-yet-released
      marking; route + Sidebar nav entry (FRG-UI-018)
- [x] 3.2 Per-entry actions on linked cards: want/skip via
      `useToggleIssueMonitored`, search via `useRunCommand('issue-search')` +
      `useWatchedCommand` with pull invalidation; no actions on unlinked
      entries (FRG-PULL-007)
- [x] 3.3 "New this week" strip from `matchType === 'new_series'` rows
      (excluded from the agenda), add affordance via `navigate('/add',
      {state: {prefillTerm}})`; strip absent when none (FRG-PULL-008)
- [x] 3.4 `CalendarScreen.test.tsx` vitest coverage, requirement IDs in test
      names: default current-week Following load, week nav parameterisation,
      scope toggle + hidden counts, derived-state projection, degraded-source
      render, action delegation (PUT + command dispatch, no pull writes),
      unlinked-no-actions, strip rendering/absence/single-appearance,
      future-week unreleased marking (FRG-UI-018, FRG-PULL-007, FRG-PULL-008,
      FRG-PULL-009)

## 4. Docs, traceability, gate

- [x] 4.1 Manual: `docs/manual/user/web-ui.md` new "Weekly pull / Calendar"
      section; README tour refreshed via `tools/refresh-readme-shots.sh`
      (sidebar gained Calendar in every shot; no dedicated calendar shot —
      see the proposal's Impact rationale) (FRG-UI-018, FRG-PROC-011/017)
- [x] 4.2 Registry flips FRG-UI-018 / FRG-PULL-007..009 → implemented;
      regenerate traceability matrix; `tools/soup_check.py` green
      (FRG-PROC-002/005)
- [x] 4.3 CHANGELOG entry + version bump ON-BRANCH (v0.4.7), e2e spine green,
      tiered review gate (medium: angles + Codex) with findings applied
      before merge (FRG-PROC-007/013)
