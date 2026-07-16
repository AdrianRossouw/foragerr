import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  makeCommand,
  makeIssue,
  makeSeriesResource,
  pageOf,
} from '../../test/mockData';
import { createQueryClient } from '../../queryClient';
import { queryKeys } from '../../api/queryKeys';
import type {
  AddSeriesNavigationState,
  PullEntryRecord,
} from '../../api/types';
import { addWeeks, currentIsoWeek, isoDateKey, weekDates, weekRangeLabel } from '../../utils/isoWeek';
import { CalendarScreen } from './CalendarScreen';

/**
 * FRG-UI-018 / FRG-PULL-007..009 — the Calendar screen: a date-grouped agenda
 * over the weekly pull projection, All-releases-scoped by default (discovery
 * first — owner decision 2026-07-11), with per-entry want/skip/search (linked
 * rows only), a new-series strip, and future-week "not yet released" marking.
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
  it('FRG-UI-018 — default load requests the current week in All-releases scope (unmatched included) and marks New Comic Day + Today', async () => {
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
      // An unfollowed, unmatched book — the default view is a discovery surface,
      // so it must render without any scope change (owner decision 2026-07-11).
      makePullRecord({
        id: 999,
        seriesName: 'Ghost Machine',
        publisher: 'Image',
        releaseDate: wedKey,
        matchType: 'unmatched',
      }),
    ];
    const { spy, fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar' });

    await screen.findByText('Saga');
    expect(spy).toHaveBeenCalledWith(pullPath(week));
    // The full week shows by default — followed and unfollowed alike.
    expect(screen.getByText('Bone')).toBeInTheDocument();
    expect(screen.getByText('Ghost Machine')).toBeInTheDocument();
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

  it('FRG-UI-018 — the Following scope narrows to library entries and All releases restores the full week', async () => {
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

    // Default All-releases scope: the unmatched row shows, with the "N followed"
    // day count alongside it (discovery first — owner decision 2026-07-11).
    expect(await screen.findByText('Ghost Machine')).toBeInTheDocument();
    expect(screen.getByText('Saga')).toBeInTheDocument();
    expect(screen.getByText('1 followed')).toBeInTheDocument();

    // Following narrows to library entries, hiding the unmatched row behind the
    // "+N more titles shipping" note.
    await user.click(screen.getByRole('radio', { name: 'Following' }));
    await waitFor(() =>
      expect(screen.queryByText('Ghost Machine')).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/\+1 more title shipping/)).toBeInTheDocument();

    // Back to All releases restores the full week with its followed count.
    await user.click(screen.getByRole('radio', { name: 'All releases' }));
    expect(await screen.findByText('Ghost Machine')).toBeInTheDocument();
    expect(screen.getByText('1 followed')).toBeInTheDocument();
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

  it('FRG-UI-018 — a malformed ?week= param falls back to the current week without crashing', async () => {
    const week = currentIsoWeek();
    const { spy, fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/series') ? pageOf([]) : pageOf([], { pageSize: 200 }),
    );
    // `?week=not-a-week` would crash the week utilities during render if fed
    // through unchecked; the screen must validate it and render the current week.
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=not-a-week' });

    await screen.findByText(/No releases this week/);
    expect(screen.getByTestId('week-range')).toHaveTextContent(weekRangeLabel(week));
    // The bad param never reached the pull endpoint — the current week was used.
    expect(spy).toHaveBeenCalledWith(pullPath(week));
    expect(spy).not.toHaveBeenCalledWith(
      expect.stringContaining('week=not-a-week'),
    );
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
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    // The lone unmatched row shows in the default All-releases scope; assert its
    // card offers no action buttons.
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

describe('FRG-PULL-008: strip suppresses already-added series', () => {
  it('FRG-PULL-008 — a debut whose title is already in the cached library index is not rendered in the strip', async () => {
    const records = [
      linkedRow('Saga', '2026-07-01'),
      makePullRecord({
        id: 1001,
        seriesName: 'Absolute Batman',
        publisher: 'DC',
        releaseDate: '2026-07-01',
        matchType: 'new_series',
      }),
      makePullRecord({
        id: 1002,
        seriesName: 'Fresh Debut',
        publisher: 'Image',
        releaseDate: '2026-07-01',
        matchType: 'new_series',
      }),
    ];
    // Seed the shared ['series'] index (as HeaderQuickSearch's useSeriesIndex
    // populates it) with a library series matching one debut, casefolded.
    const client = createQueryClient();
    client.setQueryData(queryKeys.series.all(), [
      makeSeriesResource({ id: 7, title: 'absolute batman' }),
    ]);
    const { fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/series')
        ? pageOf([makeSeriesResource({ id: 7, title: 'absolute batman' })])
        : pageOf(records, { pageSize: 200 }),
    );
    renderWithProviders(<CalendarScreen />, {
      client,
      fetcher,
      route: '/calendar?week=2026-W27',
    });

    const strip = await screen.findByTestId('new-this-week');
    // The not-yet-added debut still surfaces…
    expect(within(strip).getByText('Fresh Debut')).toBeInTheDocument();
    // …but the one already in the library is suppressed (stale "Add" gone).
    expect(screen.queryByText('Absolute Batman')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Add Absolute Batman' }),
    ).not.toBeInTheDocument();
  });
});

describe('FRG-PULL-007: search completion re-projects the week', () => {
  it('FRG-PULL-007 — a search command reaching completed refetches the pull week', async () => {
    const week = '2026-W27';
    const records = [linkedRow('Saga', '2026-07-01')];
    const { spy, fetcher } = fakeFetcher((path, init) => {
      if (init?.method === 'POST' && path === '/api/v1/command') {
        return makeCommand({ id: 90, name: 'issue-search', status: 'queued' });
      }
      if (path === '/api/v1/command/90') {
        // First (and only) poll returns terminal → onFinished('completed') fires.
        return makeCommand({ id: 90, name: 'issue-search', status: 'completed' });
      }
      if (path.startsWith('/api/v1/series')) return pageOf([]);
      return pageOf(records, { pageSize: 200 });
    });
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: `/calendar?week=${week}` });

    await screen.findByText('Saga');
    const pullCallsBefore = spy.mock.calls.filter(([p]) => p === pullPath(week)).length;

    await user.click(screen.getByRole('button', { name: 'Search for Saga' }));

    // The completed-command branch invalidates ['pull'] → the week refetches.
    await waitFor(() => {
      const pullCallsAfter = spy.mock.calls.filter(([p]) => p === pullPath(week)).length;
      expect(pullCallsAfter).toBeGreaterThan(pullCallsBefore);
    });
    expect(screen.getByTestId('command-status')).toHaveTextContent('completed');
  });
});

describe('FRG-UI-018: publisher filter + banner', () => {
  it('FRG-UI-018 — selecting a publisher filters the cards, counts, and banner scope', async () => {
    const records = [
      linkedRow('Saga', '2026-07-01', { publisher: 'Image' }),
      linkedRow('Batman', '2026-07-01', {
        publisher: 'DC',
        matchedIssueId: 501,
        series: { id: 8, title: 'Batman' },
      }),
      // An unmatched Image row so the Following banner shows a nonzero "more".
      makePullRecord({
        id: 999,
        seriesName: 'Ghost Machine',
        publisher: 'Image',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
      }),
    ];
    const { fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/series') ? pageOf([]) : pageOf(records, { pageSize: 200 }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Saga');
    // In the DEFAULT All-releases scope, an active publisher filter must be
    // named in the banner too (gate finding, calendar-discovery-default) —
    // "Showing all N ... from DC", never an unqualified whole-week claim.
    await user.selectOptions(screen.getByLabelText('Filter by publisher'), 'DC');
    await waitFor(() =>
      expect(
        screen.getByText(/Showing all 1 single issue shipping this week from DC/),
      ).toBeInTheDocument(),
    );
    await user.selectOptions(screen.getByLabelText('Filter by publisher'), 'all');
    // The richer publisher-suffix arithmetic below is a Following-scope
    // affordance, so the rest of the test drives the filter from Following.
    await user.click(screen.getByRole('radio', { name: 'Following' }));
    // Following scope: 2 followed issues (Saga + Batman), 1 unmatched → banner
    // reports "1 more titles ... across every publisher" (no filter yet).
    const banner = () => screen.getByText(/Comics ship in one big weekly drop/);
    expect(banner()).toHaveTextContent('the 2 issues from series you follow');
    expect(banner()).toHaveTextContent('1 more titles ship this week across every publisher');

    // Filter to DC: only Batman survives; Saga + the Image unmatched row vanish.
    await user.selectOptions(screen.getByLabelText('Filter by publisher'), 'DC');
    await waitFor(() =>
      expect(screen.queryByText('Saga')).not.toBeInTheDocument(),
    );
    expect(screen.getByText('Batman')).toBeInTheDocument();
    // The day count now reflects only DC's single followed issue.
    expect(screen.getByText('1 issue')).toBeInTheDocument();
    // Banner is scoped to the selected publisher, not "across every publisher".
    expect(banner()).toHaveTextContent('the 1 issue from series you follow');
    expect(banner()).toHaveTextContent('0 more titles ship this week from DC');
    expect(banner()).not.toHaveTextContent('across every publisher');
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

describe('FRG-UI-035: Calendar degraded pull-source notice', () => {
  const week = currentIsoWeek();

  /** A path-aware fetcher: pull weeks resolve to `records`, the system-health
   *  endpoint to `healthComponents`, everything else to an empty page. */
  function resolver(
    records: PullEntryRecord[],
    healthComponents: unknown,
  ) {
    return (path: string) => {
      if (path === '/api/v1/system/health') return healthComponents;
      if (path.startsWith('/api/v1/pull')) return pageOf(records, { pageSize: 200 });
      return pageOf([], { pageSize: 200 });
    };
  }

  it('FRG-UI-035 — a degraded pull source renders the inline degraded notice', async () => {
    const { fetcher } = fakeFetcher(
      resolver(
        [],
        [
          {
            component: 'pull-source',
            label: 'Weekly pull source',
            state: 'degraded',
            message: 'Weekly pull source is degraded after 3 failed fetch(es)',
            last_success: null,
            last_failure: null,
            disabled_until: null,
          },
        ],
      ),
    );
    renderWithProviders(<CalendarScreen />, { fetcher, route: `/calendar?week=${week}` });

    const notice = await screen.findByTestId('calendar-degraded-notice');
    expect(notice).toHaveTextContent(/weekly pull source is currently unavailable/i);
    expect(notice).toHaveTextContent(/library’s own data only/i);
  });

  it('FRG-UI-035 — a healthy source (no pull-source component) renders no notice', async () => {
    // Health payload with only OTHER components: the pull-source component is
    // absent when healthy, so no notice renders.
    const { fetcher } = fakeFetcher(
      resolver(
        [],
        [
          {
            component: 'comicvine',
            label: 'ComicVine',
            state: 'ok',
            message: null,
            last_success: null,
            last_failure: null,
            disabled_until: null,
          },
        ],
      ),
    );
    renderWithProviders(<CalendarScreen />, { fetcher, route: `/calendar?week=${week}` });

    await screen.findByText(/No releases this week/);
    expect(screen.queryByTestId('calendar-degraded-notice')).not.toBeInTheDocument();
  });

  it('FRG-UI-035 — pull disabled (empty health payload) renders no notice', async () => {
    // A disabled pull source contributes no health component at all, which is
    // indistinguishable from healthy here — either way, no notice.
    const { fetcher } = fakeFetcher(resolver([], []));
    renderWithProviders(<CalendarScreen />, { fetcher, route: `/calendar?week=${week}` });

    await screen.findByText(/No releases this week/);
    expect(screen.queryByTestId('calendar-degraded-notice')).not.toBeInTheDocument();
  });
});
