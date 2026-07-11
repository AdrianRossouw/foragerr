import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { makeCommand, makeIssue, pageOf } from '../../test/mockData';
import type {
  AddSeriesNavigationState,
  PullEntryRecord,
} from '../../api/types';
import { addWeeks, currentIsoWeek, isoDateKey, weekDates, weekRangeLabel } from '../../utils/isoWeek';
import { CalendarScreen } from './CalendarScreen';

/**
 * FRG-UI-018 / FRG-PULL-007..009 — the Calendar screen: a date-grouped agenda
 * over the weekly pull projection, Following-scoped by default, with per-entry
 * want/skip/search (linked rows only), a new-series strip, and future-week
 * "not yet released" marking.
 */

function makePullRecord(
  overrides: Partial<PullEntryRecord> & Pick<PullEntryRecord, 'seriesName'>,
): PullEntryRecord {
  return {
    id: null,
    week: '2026-W27',
    publisher: 'Image',
    issueNumber: '1',
    releaseDate: null,
    cvSeriesId: null,
    cvIssueId: null,
    matchType: null,
    matchedIssueId: null,
    state: null,
    series: null,
    issue: null,
    ...overrides,
  };
}

const pullPath = (week: string, page = 1) =>
  `/api/v1/pull?week=${week}&page=${page}&pageSize=200&sortKey=release_date&sortDirection=asc`;

/** A linked, monitored/missing library row keyed to a day. */
function linkedRow(name: string, releaseDate: string, over: Partial<PullEntryRecord> = {}) {
  return makePullRecord({
    seriesName: name,
    releaseDate,
    matchType: 'id',
    matchedIssueId: 500,
    state: 'missing_wanted',
    series: { id: 7, title: name },
    issue: { id: 500, issueNumber: '1', title: null },
    ...over,
  });
}

describe('FRG-UI-018: Calendar agenda', () => {
  it('FRG-UI-018 — default load requests the current week in Following scope and marks New Comic Day + Today', async () => {
    const week = currentIsoWeek();
    const days = weekDates(week);
    const wedKey = isoDateKey(days[2]); // Wednesday
    const todayKey = isoDateKey(
      new Date(
        Date.UTC(new Date().getUTCFullYear(), new Date().getUTCMonth(), new Date().getUTCDate()),
      ),
    );
    const records = [
      linkedRow('Saga', wedKey),
      linkedRow('Bone', todayKey, { matchedIssueId: 501, series: { id: 8, title: 'Bone' } }),
    ];
    const { spy, fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar' });

    await screen.findByText('Saga');
    expect(spy).toHaveBeenCalledWith(pullPath(week));
    expect(screen.getByText('New Comic Day')).toBeInTheDocument();
    expect(screen.getByText('Today')).toBeInTheDocument();
    expect(screen.getByTestId('week-range')).toHaveTextContent(weekRangeLabel(week));
  });

  it('FRG-UI-018 — week navigation parameterises the query and This Week returns to now', async () => {
    const week = currentIsoWeek();
    const { spy, fetcher } = fakeFetcher(() => pageOf([], { pageSize: 200 }));
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar' });

    await screen.findByText(/No releases this week/);
    await user.click(screen.getByRole('button', { name: 'Next week' }));
    await waitFor(() =>
      expect(screen.getByTestId('week-range')).toHaveTextContent(
        weekRangeLabel(addWeeks(week, 1)),
      ),
    );
    expect(spy).toHaveBeenCalledWith(pullPath(addWeeks(week, 1)));

    await user.click(screen.getByRole('button', { name: 'Next week' }));
    await waitFor(() =>
      expect(screen.getByTestId('week-range')).toHaveTextContent(
        weekRangeLabel(addWeeks(week, 2)),
      ),
    );

    await user.click(screen.getByRole('button', { name: 'This Week' }));
    await waitFor(() =>
      expect(screen.getByTestId('week-range')).toHaveTextContent(weekRangeLabel(week)),
    );
  });

  it('FRG-UI-018 — the All-releases scope reveals unmatched entries with followed/hidden counts', async () => {
    // Fixed week (2026-W27, Wed = Jul 1) so "today" never interferes.
    const records = [
      linkedRow('Saga', '2026-07-01'),
      makePullRecord({
        id: 999,
        seriesName: 'Ghost Machine',
        publisher: 'Image',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Saga');
    // Following scope hides the unmatched row behind a hidden-count note.
    expect(screen.queryByText('Ghost Machine')).not.toBeInTheDocument();
    expect(screen.getByText(/\+1 more title shipping/)).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: 'All releases' }));
    expect(await screen.findByText('Ghost Machine')).toBeInTheDocument();
    expect(screen.getByText('1 followed')).toBeInTheDocument();

    // Switching back hides it again.
    await user.click(screen.getByRole('radio', { name: 'Following' }));
    await waitFor(() =>
      expect(screen.queryByText('Ghost Machine')).not.toBeInTheDocument(),
    );
  });

  it('FRG-UI-018 — a degraded/empty pull source still renders the library-primary rows', async () => {
    // Pure library-primary rows (id null, matchType null) — what the projection
    // yields when no pull source is configured or its last fetch failed.
    const records = [
      makePullRecord({
        seriesName: 'Invincible',
        publisher: 'Image',
        releaseDate: '2026-07-01',
        matchedIssueId: 71,
        state: 'missing_wanted',
        series: { id: 7, title: 'Invincible' },
        issue: { id: 71, issueNumber: '1', title: null },
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    expect(await screen.findByText('Invincible')).toBeInTheDocument();
    expect(screen.queryByText('Could not load the weekly release list.')).not.toBeInTheDocument();
    expect(screen.queryByText(/No releases this week/)).not.toBeInTheDocument();
  });

  it('FRG-UI-018 — an error is distinct from the empty state', async () => {
    const { fetcher } = fakeFetcher(() => {
      throw new Error('boom');
    });
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    expect(
      await screen.findByText('Could not load the weekly release list.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/No releases this week/)).not.toBeInTheDocument();
  });
});

describe('FRG-PULL-007: Calendar per-entry actions', () => {
  it('FRG-PULL-007 — want toggles the linked issue via PUT /api/v1/issues/{id} and writes nothing pull-side', async () => {
    const records = [
      linkedRow('Saga', '2026-07-01', { state: 'unmonitored', matchedIssueId: 500 }),
    ];
    const { spy, fetcher } = fakeFetcher((path, init) => {
      if (init?.method === 'PUT' && path === '/api/v1/issues/500') {
        return makeIssue({ id: 500, series_id: 7, monitored: true });
      }
      return pageOf(records, { pageSize: 200 });
    });
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Saga');
    await user.click(screen.getByRole('button', { name: 'Want Saga' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/issues/500', {
        method: 'PUT',
        body: { monitored: true },
      }),
    );
    // No pull-side write endpoint exists; the only mutating call is the issue PUT.
    const mutating = spy.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET');
    expect(mutating).toHaveLength(1);
  });

  it('FRG-PULL-007 — search dispatches an issue-search command with the linked ids', async () => {
    const records = [linkedRow('Saga', '2026-07-01')];
    const { spy, fetcher } = fakeFetcher((path, init) => {
      if (init?.method === 'POST' && path === '/api/v1/command') {
        return makeCommand({ id: 90, name: 'issue-search', status: 'queued' });
      }
      if (path === '/api/v1/command/90') {
        return makeCommand({ id: 90, name: 'issue-search', status: 'started' });
      }
      return pageOf(records, { pageSize: 200 });
    });
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Saga');
    await user.click(screen.getByRole('button', { name: 'Search for Saga' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/command', {
        method: 'POST',
        body: { name: 'issue-search', payload: { series_id: 7, issue_id: 500 } },
      }),
    );
  });

  it('FRG-PULL-007 — unlinked entries expose no want/skip or search actions', async () => {
    const records = [
      makePullRecord({
        id: 999,
        seriesName: 'Ghost Machine',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    // The lone unmatched row is hidden in the default Following scope; switch to
    // All releases to reveal it, then assert its card offers no action buttons.
    await screen.findByTestId('week-range');
    await user.click(screen.getByRole('radio', { name: 'All releases' }));
    const card = await screen.findByTestId('calendar-card-999');
    expect(within(card).queryAllByRole('button')).toHaveLength(0);
  });
});

describe('FRG-PULL-008: New-series strip', () => {
  it('FRG-PULL-008 — a new-series debut renders once in the strip (not the agenda) with an add hand-off', async () => {
    const records = [
      linkedRow('Saga', '2026-07-01'),
      makePullRecord({
        id: 1001,
        seriesName: 'Absolute Batman',
        publisher: 'DC',
        issueNumber: '1',
        releaseDate: '2026-07-01',
        matchType: 'new_series',
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));

    function AddProbe() {
      const state = useLocation().state as AddSeriesNavigationState | null;
      return <div data-testid="add-probe">{state?.prefillTerm}</div>;
    }
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter initialEntries={['/calendar?week=2026-W27']}>
        <Routes>
          <Route path="/calendar" element={<CalendarScreen />} />
          <Route path="/add" element={<AddProbe />} />
        </Routes>
      </MemoryRouter>,
      { fetcher, withRouter: false },
    );

    const strip = await screen.findByTestId('new-this-week');
    expect(within(strip).getByText('Absolute Batman')).toBeInTheDocument();
    // Exactly once — surfaced in the strip, excluded from the day agenda.
    expect(screen.getAllByText('Absolute Batman')).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: 'Add Absolute Batman' }));
    expect(await screen.findByTestId('add-probe')).toHaveTextContent('Absolute Batman');
  });

  it('FRG-PULL-008 — no new-series entries means no strip at all', async () => {
    const records = [linkedRow('Saga', '2026-07-01')];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Saga');
    expect(screen.queryByTestId('new-this-week')).not.toBeInTheDocument();
  });
});

describe('FRG-PULL-009: Future-week presentation', () => {
  it('FRG-PULL-009 — a future-week entry renders marked not-yet-released', async () => {
    const futureWeek = addWeeks(currentIsoWeek(), 4);
    const futureDay = isoDateKey(weekDates(futureWeek)[2]);
    const records = [linkedRow('Saga', futureDay)];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, {
      fetcher,
      route: `/calendar?week=${futureWeek}`,
    });

    await screen.findByText('Saga');
    expect(screen.getByText('Not yet released')).toBeInTheDocument();
    const card = screen.getByText('Saga').closest('[data-future]');
    expect(card).toHaveAttribute('data-future', 'true');
  });
});
