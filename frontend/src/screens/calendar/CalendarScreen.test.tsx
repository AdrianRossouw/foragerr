import { describe, it, expect } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  makeCommand,
  makeIssue,
  makeLinkedPullEntry,
  makePullEntry,
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
import {
  PUBLISHER_ACCENT,
  PUBLISHER_ACCENT_DEFAULT,
  publisherAccent,
} from '../../theme/palettes';
import { CalendarScreen } from './CalendarScreen';

/**
 * FRG-UI-018 / FRG-PULL-007..009 / FRG-UI-042 — the Calendar screen: a
 * date-grouped agenda over the weekly pull projection, All-releases-scoped by
 * default (discovery first — owner decision 2026-07-11), with per-entry
 * want/skip/search (linked rows only), an add affordance on every unlinked
 * entry whose series is not already in the library, inline "New" debut badges
 * behind a debuts-only filter, stored covers + enrichment detail, and
 * future-week "not yet released" marking.
 */

const pullPath = (week: string, page = 1) =>
  `/api/v1/pull?week=${week}&page=${page}&pageSize=200&sortKey=release_date&sortDirection=asc`;

describe('FRG-UI-018: Calendar agenda', () => {
  it('FRG-UI-018 — default load requests the current week in All-releases scope (unmatched included) and marks New Comic Day + Today', async () => {
    const week = currentIsoWeek();
    const days = weekDates(week);
    const wedKey = isoDateKey(days[2]); // Wednesday
    // LOCAL y/m/d, mirroring the screen's own todayKey — near a day boundary
    // the UTC date differs and the Today badge lands on a day this fixture
    // would otherwise leave rowless.
    const now = new Date();
    const todayKey = isoDateKey(
      new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())),
    );
    const records = [
      makeLinkedPullEntry('Saga', { releaseDate: wedKey }),
      makeLinkedPullEntry('Bone', {
        releaseDate: todayKey,
        matchedIssueId: 501,
        series: { id: 8, title: 'Bone' },
      }),
      // An unfollowed, unmatched book — the default view is a discovery surface,
      // so it must render without any scope change (owner decision 2026-07-11).
      makePullEntry({
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
      makeLinkedPullEntry('Saga', { releaseDate: '2026-07-01' }),
      makePullEntry({
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
      makePullEntry({
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
      makeLinkedPullEntry('Saga', {
        releaseDate: '2026-07-01',
        state: 'unmonitored',
        matchedIssueId: 500,
      }),
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
    await user.click(screen.getByRole('button', { name: 'Monitor Saga' }));

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
    const records = [makeLinkedPullEntry('Saga', { releaseDate: '2026-07-01' })];
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
      makePullEntry({
        id: 999,
        seriesName: 'Ghost Machine',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    // The lone unmatched row shows in the default All-releases scope; assert its
    // card offers none of the linked-row issue actions. (Its add hand-off — an
    // unlinked-row affordance, FRG-PULL-008 — is asserted separately.)
    const card = await screen.findByTestId('calendar-card-999');
    expect(
      within(card).queryByRole('button', { name: /^(Want|Skip) / }),
    ).not.toBeInTheDocument();
    expect(
      within(card).queryByRole('button', { name: /^Search for / }),
    ).not.toBeInTheDocument();
  });
});

/**
 * The Add hand-off's navigation state, read back at the /add route: the shape
 * the Calendar emits is the contract the Add screen's id-first resolution
 * consumes (FRG-PULL-008 / FRG-API-026).
 */
function AddProbe() {
  const state = useLocation().state as AddSeriesNavigationState | null;
  return (
    <div data-testid="add-probe">
      <span data-testid="probe-term">{state?.prefillTerm ?? ''}</span>
      <span data-testid="probe-cv-id">
        {state?.prefillCvVolumeId === undefined
          ? 'none'
          : String(state.prefillCvVolumeId)}
      </span>
    </div>
  );
}

describe('FRG-PULL-008: add-from-anywhere hand-off', () => {
  /** Mounts the Calendar with a real /add route so the navigation state is
   *  observable exactly as the Add screen would receive it. */
  function renderWithAddProbe(fetcher: ReturnType<typeof fakeFetcher>['fetcher']) {
    renderWithProviders(
      <MemoryRouter initialEntries={['/calendar?week=2026-W27']}>
        <Routes>
          <Route path="/calendar" element={<CalendarScreen />} />
          <Route path="/add" element={<AddProbe />} />
        </Routes>
      </MemoryRouter>,
      { fetcher, withRouter: false },
    );
  }

  it('FRG-PULL-008 — a mid-run unmatched entry for an unknown series offers Add and hands over its ComicVine series id', async () => {
    const records = [
      makeLinkedPullEntry('Nocturne Atlas', { releaseDate: '2026-07-01' }),
      makePullEntry({
        id: 2001,
        seriesName: 'Tidewrack',
        publisher: 'Umbral Press',
        // Mid-run, not a debut — the widened affordance's whole point.
        issueNumber: '14',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
        cvSeriesId: 154217,
      }),
    ];
    const { spy, fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    const user = userEvent.setup();
    renderWithAddProbe(fetcher);

    await screen.findByText('Tidewrack');
    await user.click(screen.getByRole('button', { name: 'Add Tidewrack' }));

    const probe = await screen.findByTestId('add-probe');
    expect(within(probe).getByTestId('probe-cv-id')).toHaveTextContent('154217');
    expect(within(probe).getByTestId('probe-term')).toHaveTextContent('Tidewrack');
    // Navigation only — the Calendar never writes (no auto-add, FRG-PULL-008).
    const mutating = spy.mock.calls.filter(
      ([, init]) => init?.method && init.method !== 'GET',
    );
    expect(mutating).toHaveLength(0);
  });

  it('FRG-PULL-008 — an entry without a ComicVine series id hands over the name alone', async () => {
    const records = [
      makePullEntry({
        id: 2002,
        seriesName: 'Hollow Signal',
        publisher: 'Umbral Press',
        issueNumber: '7',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
        cvSeriesId: null,
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    const user = userEvent.setup();
    renderWithAddProbe(fetcher);

    await screen.findByText('Hollow Signal');
    await user.click(screen.getByRole('button', { name: 'Add Hollow Signal' }));

    const probe = await screen.findByTestId('add-probe');
    expect(within(probe).getByTestId('probe-cv-id')).toHaveTextContent('none');
    expect(within(probe).getByTestId('probe-term')).toHaveTextContent(
      'Hollow Signal',
    );
  });

  it('FRG-PULL-008 — an unlinked entry whose series is already in the library offers no Add', async () => {
    const records = [
      makePullEntry({
        id: 2003,
        seriesName: 'Tidewrack',
        publisher: 'Umbral Press',
        issueNumber: '14',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
      }),
      makePullEntry({
        id: 2004,
        seriesName: 'Hollow Signal',
        publisher: 'Umbral Press',
        issueNumber: '1',
        releaseDate: '2026-07-01',
        matchType: 'new_series',
      }),
    ];
    // Seed the shared ['series'] index (as HeaderQuickSearch's useSeriesIndex
    // populates it) with a library series matching one entry, casefolded.
    const client = createQueryClient();
    client.setQueryData(queryKeys.series.all(), [
      makeSeriesResource({ id: 7, title: 'tidewrack' }),
    ]);
    const { fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/series')
        ? pageOf([makeSeriesResource({ id: 7, title: 'tidewrack' })])
        : pageOf(records, { pageSize: 200 }),
    );
    renderWithProviders(<CalendarScreen />, {
      client,
      fetcher,
      route: '/calendar?week=2026-W27',
    });

    // Both entries still render in the agenda…
    expect(await screen.findByText('Tidewrack')).toBeInTheDocument();
    expect(screen.getByText('Hollow Signal')).toBeInTheDocument();
    // …but only the one the library does not already carry offers Add.
    expect(
      screen.getByRole('button', { name: 'Add Hollow Signal' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Add Tidewrack' }),
    ).not.toBeInTheDocument();
  });

  it('FRG-PULL-008 — a linked entry offers no Add, only its issue actions', async () => {
    const records = [
      makeLinkedPullEntry('Nocturne Atlas', { releaseDate: '2026-07-01' }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Nocturne Atlas');
    expect(
      screen.queryByRole('button', { name: 'Add Nocturne Atlas' }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Search for Nocturne Atlas' }),
    ).toBeInTheDocument();
  });
});

describe('FRG-PULL-008: inline debuts + debut filter', () => {
  const records = [
    makeLinkedPullEntry('Nocturne Atlas', { releaseDate: '2026-07-01' }),
    makePullEntry({
      id: 2101,
      seriesName: 'Hollow Signal',
      publisher: 'Umbral Press',
      issueNumber: '1',
      releaseDate: '2026-07-01',
      matchType: 'new_series',
      cvSeriesId: 90210,
    }),
  ];

  it('FRG-PULL-008 — a debut renders inline in the day agenda with a New badge and no separate strip', async () => {
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    const agenda = await screen.findByTestId('calendar-agenda');
    // In date position inside the agenda — exactly once, never a second stack.
    expect(within(agenda).getByText('Hollow Signal')).toBeInTheDocument();
    expect(screen.getAllByText('Hollow Signal')).toHaveLength(1);
    expect(screen.queryByTestId('new-this-week')).not.toBeInTheDocument();
    expect(screen.queryByText('New this week')).not.toBeInTheDocument();
    // Badged as a debut, and addable like any other unlinked entry.
    expect(screen.getByTestId('calendar-new-badge-2101')).toHaveTextContent('New');
    expect(
      screen.getByRole('button', { name: 'Add Hollow Signal' }),
    ).toBeInTheDocument();
    // The linked, non-debut row carries no badge — the debut's is the only one.
    expect(screen.getAllByText('New')).toHaveLength(1);
  });

  it('FRG-PULL-008 — the debut filter narrows the agenda to badge-carrying entries and back', async () => {
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Hollow Signal');
    expect(screen.getByText('Nocturne Atlas')).toBeInTheDocument();

    const toggle = screen.getByRole('button', { name: /New series only/ });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await user.click(toggle);

    await waitFor(() =>
      expect(screen.queryByText('Nocturne Atlas')).not.toBeInTheDocument(),
    );
    expect(screen.getByText('Hollow Signal')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /New series only/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    await user.click(screen.getByRole('button', { name: /New series only/ }));
    expect(await screen.findByText('Nocturne Atlas')).toBeInTheDocument();
  });

  it('FRG-PULL-008 — the banner headline count matches the rendered cards once debutsOnly is active', async () => {
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Hollow Signal');
    // Before the toggle: both cards render, and the banner's headline (2)
    // matches them.
    expect(
      screen.getByText(/Showing all 2 single issues shipping this week/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /New series only/ }));
    await waitFor(() =>
      expect(screen.queryByText('Nocturne Atlas')).not.toBeInTheDocument(),
    );
    // Only one card renders now (the debut) — the banner headline must track
    // that rendered count, not the pre-debutsOnly-filter week total of 2.
    const agenda = screen.getByTestId('calendar-agenda');
    expect(within(agenda).getAllByTestId(/^calendar-card-/)).toHaveLength(1);
    expect(
      screen.getByText(/Showing all 1 single issue shipping this week/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Showing all 2 single issues shipping this week/),
    ).not.toBeInTheDocument();
  });

  it('FRG-PULL-008 — the debuts-only toggle reflects debuts in the CURRENT scope, not the whole week', async () => {
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Hollow Signal');
    // All-releases scope: one debut in scope, so the toggle advertises it.
    expect(screen.getByRole('button', { name: /New series only/ })).toHaveTextContent(
      '1',
    );

    // A `new_series` entry is never "following" (no matched issue -> no
    // series -> isFollowing false), so Following scope has zero debuts in
    // scope — the toggle must not offer a filter that would yield the empty
    // state, so it disappears rather than advertise a phantom count.
    await user.click(screen.getByRole('radio', { name: 'Following' }));
    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: /New series only/ }),
      ).not.toBeInTheDocument(),
    );
  });

  it('FRG-PULL-008 — a debut-free week offers no debuts-only toggle at all', async () => {
    const noDebutRecords = [
      makeLinkedPullEntry('Nocturne Atlas', { releaseDate: '2026-07-01' }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(noDebutRecords, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Nocturne Atlas');
    expect(
      screen.queryByRole('button', { name: /New series only/ }),
    ).not.toBeInTheDocument();
  });
});

describe('FRG-UI-042: Calendar covers and enrichment detail', () => {
  const COVER_URL =
    'https://s3.amazonaws.com/comicgeeks/comics/covers/large-24680.jpg';

  const enriched = makePullEntry({
    id: 3001,
    seriesName: 'Tidewrack',
    publisher: 'Umbral Press',
    issueNumber: '14',
    releaseDate: '2026-07-01',
    matchType: 'unmatched',
    coverUrl: COVER_URL,
    description: 'A dredging crew hauls up something that remembers them.',
    creators: [
      { role: 'Writer', name: 'A. Marlowe' },
      { role: 'Artist', name: 'R. Vance' },
    ],
    characters: [{ name: 'Sable Quill' }],
    upc: '76194138888801411',
  });

  it('FRG-UI-042 — a stored cover renders lazily through the same-origin cover proxy', async () => {
    const { fetcher } = fakeFetcher(() => pageOf([enriched], { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Tidewrack');
    const img = screen.getByRole('img', { name: 'Tidewrack cover' });
    expect(img).toHaveAttribute(
      'src',
      `/api/v1/metadata/cover?src=${encodeURIComponent(COVER_URL)}`,
    );
    expect(img).toHaveAttribute('loading', 'lazy');
  });

  it('FRG-UI-042 — an entry with no stored cover renders the publisher spine, never a broken image', async () => {
    const records = [
      makePullEntry({
        id: 3002,
        seriesName: 'Hollow Signal',
        publisher: 'Umbral Press',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
        coverUrl: null,
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Hollow Signal');
    const card = screen.getByTestId('calendar-card-3002');
    expect(within(card).queryByRole('img')).not.toBeInTheDocument();
    expect(card.querySelector('img')).toBeNull();
  });

  it('FRG-UI-042 — a cover whose proxy fetch errors falls back to the spine in place', async () => {
    const { fetcher } = fakeFetcher(() => pageOf([enriched], { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Tidewrack');
    const img = screen.getByRole('img', { name: 'Tidewrack cover' });
    fireEvent.error(img);

    await waitFor(() =>
      expect(
        screen.queryByRole('img', { name: 'Tidewrack cover' }),
      ).not.toBeInTheDocument(),
    );
    // The row itself is untouched — only its imagery degraded.
    expect(screen.getByText('Tidewrack')).toBeInTheDocument();
  });

  it('FRG-UI-042 — the detail surface exposes description, creators, characters and UPC', async () => {
    const { fetcher } = fakeFetcher(() => pageOf([enriched], { pageSize: 200 }));
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Tidewrack');
    expect(screen.queryByTestId('calendar-detail-3001')).not.toBeInTheDocument();

    await user.click(
      screen.getByRole('button', { name: 'Show details for Tidewrack' }),
    );
    const detail = await screen.findByTestId('calendar-detail-3001');
    expect(detail).toHaveTextContent(
      'A dredging crew hauls up something that remembers them.',
    );
    expect(detail).toHaveTextContent('A. Marlowe (Writer)');
    expect(detail).toHaveTextContent('R. Vance (Artist)');
    expect(detail).toHaveTextContent('Sable Quill');
    expect(detail).toHaveTextContent('76194138888801411');

    await user.click(
      screen.getByRole('button', { name: 'Hide details for Tidewrack' }),
    );
    await waitFor(() =>
      expect(screen.queryByTestId('calendar-detail-3001')).not.toBeInTheDocument(),
    );
  });

  it('FRG-UI-042 — absent enrichment fields are omitted rather than rendered empty', async () => {
    const records = [
      makePullEntry({
        id: 3003,
        seriesName: 'Hollow Signal',
        publisher: 'Umbral Press',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
        description: 'A radio mast answers back.',
        creators: [{ role: 'Writer', name: 'A. Marlowe' }],
        // No characters, no UPC — those rows must not render at all.
        characters: [],
        upc: null,
      }),
      // Nothing stored at all: the entry offers no detail affordance.
      makePullEntry({
        id: 3004,
        seriesName: 'Nocturne Atlas',
        publisher: 'Umbral Press',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Hollow Signal');
    await user.click(
      screen.getByRole('button', { name: 'Show details for Hollow Signal' }),
    );
    const detail = await screen.findByTestId('calendar-detail-3003');
    expect(detail).toHaveTextContent('A radio mast answers back.');
    expect(detail).toHaveTextContent('A. Marlowe (Writer)');
    expect(detail).not.toHaveTextContent('Characters');
    expect(detail).not.toHaveTextContent('UPC');

    expect(
      screen.queryByRole('button', { name: 'Show details for Nocturne Atlas' }),
    ).not.toBeInTheDocument();
  });

  it('FRG-UI-042 — rendering covers and enrichment issues no ComicVine lookup', async () => {
    const { spy, fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/series')
        ? pageOf([])
        : pageOf([enriched], { pageSize: 200 }),
    );
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Tidewrack');
    await user.click(
      screen.getByRole('button', { name: 'Show details for Tidewrack' }),
    );
    await screen.findByTestId('calendar-detail-3001');

    // The week's imagery and enrichment come from the pull row itself — no
    // ComicVine-backed request is issued on their behalf (FRG-META-022 lanes
    // are not involved).
    const cvCalls = spy.mock.calls.filter(
      ([path]) =>
        path.includes('comicvine') || path.startsWith('/api/v1/series/lookup'),
    );
    expect(cvCalls).toHaveLength(0);
  });

  it('FRG-UI-042 — the detail description is stripped of markup and visually clamped', async () => {
    // Untrusted ComicVine deck text (same as the Add-series candidate card) —
    // residual markup must never reach the DOM, and a maximal (backend-capped
    // at 4000 chars) description must not blow out the card past a 2-line clamp.
    const description = '<b>x</b>' + ' filler word'.repeat(200);
    const records = [
      makePullEntry({
        id: 4001,
        seriesName: 'Marrow Line',
        publisher: 'Umbral Press',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
        description,
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Marrow Line');
    await user.click(
      screen.getByRole('button', { name: 'Show details for Marrow Line' }),
    );
    const detail = await screen.findByTestId('calendar-detail-4001');

    const deck = detail.querySelector('p');
    expect(deck).not.toBeNull();
    // stripHtml (the exact helper AddSeries' candidate card uses) reduces the
    // markup to plain text — no literal tag reaches the DOM.
    expect(deck!.innerHTML).not.toContain('<b>');
    expect(deck!.textContent?.startsWith('x filler word')).toBe(true);
    // The same 2-line clamp idiom as AddSeries' `.deck` bounds a maximal
    // description's visual height.
    expect(deck!.className).toMatch(/detailDeck/);
  });

  it('FRG-UI-042 — a repaired coverUrl on the same row id remounts and retries rather than staying stuck on the spine', async () => {
    const brokenUrl = 'https://s3.amazonaws.com/comicgeeks/comics/covers/broken.jpg';
    const fixedUrl = 'https://s3.amazonaws.com/comicgeeks/comics/covers/fixed.jpg';
    let coverUrl = brokenUrl;
    const records = () => [
      makePullEntry({
        id: 5001,
        seriesName: 'Marrow Line',
        publisher: 'Umbral Press',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
        coverUrl,
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records(), { pageSize: 200 }));
    const client = createQueryClient();
    renderWithProviders(<CalendarScreen />, {
      fetcher,
      client,
      route: '/calendar?week=2026-W27',
    });

    await screen.findByText('Marrow Line');
    const brokenImg = screen.getByRole('img', { name: 'Marrow Line cover' });
    fireEvent.error(brokenImg);
    await waitFor(() =>
      expect(
        screen.queryByRole('img', { name: 'Marrow Line cover' }),
      ).not.toBeInTheDocument(),
    );

    // The same row id refetches with a repaired coverUrl — the sticky
    // `failed` flag must not keep forcing the spine now that the URL differs.
    coverUrl = fixedUrl;
    await client.invalidateQueries({ queryKey: queryKeys.pull.all() });
    const repairedImg = await screen.findByRole('img', {
      name: 'Marrow Line cover',
    });
    expect(repairedImg).toHaveAttribute(
      'src',
      `/api/v1/metadata/cover?src=${encodeURIComponent(fixedUrl)}`,
    );
  });
});

describe('FRG-UI-042: the shelf row carries the publisher, creators and a teaser', () => {
  /** The chip's swatch — the element the palette accent is painted on. */
  function swatchOf(chip: HTMLElement): HTMLElement {
    return chip.querySelector('[aria-hidden]') as HTMLElement;
  }

  it('FRG-UI-042 — a live publisher name renders normalized on the chip in its palette color', async () => {
    // The feed says "Marvel Comics"; the palette is keyed "Marvel". Before the
    // normalized lookup this row drew the brand accent like every other one.
    const records = [
      makePullEntry({
        id: 6001,
        seriesName: 'Meridian Signal',
        publisher: 'Marvel Comics',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Meridian Signal');
    const chip = screen.getByTestId('calendar-publisher-6001');
    expect(chip).toHaveTextContent('Marvel');
    expect(chip).not.toHaveTextContent('Comics');
    expect(swatchOf(chip)).toHaveStyle({
      backgroundColor: PUBLISHER_ACCENT.Marvel,
    });
  });

  it('FRG-UI-042 — a publisher outside the named palette still gets its own swatch color', async () => {
    const records = [
      makePullEntry({
        id: 6002,
        seriesName: 'Tidewrack Survey',
        publisher: 'Umbral Press',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Tidewrack Survey');
    const chip = screen.getByTestId('calendar-publisher-6002');
    expect(chip).toHaveTextContent('Umbral Press');
    // Its own derived hue, never the app's accent standing in for a publisher.
    expect(swatchOf(chip)).toHaveStyle({
      backgroundColor: publisherAccent('Umbral Press'),
    });
    expect(swatchOf(chip)).not.toHaveStyle({
      backgroundColor: PUBLISHER_ACCENT_DEFAULT,
    });
  });

  it('FRG-UI-042 — the creator line names the writer then the artist, at most two apiece', async () => {
    const records = [
      makePullEntry({
        id: 6003,
        seriesName: 'Tidewrack Survey',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
        creators: [
          { role: 'Letterer', name: 'D. Quill' },
          { role: 'Writer', name: 'A. Marlowe' },
          { role: 'Writer', name: 'B. Osgood' },
          { role: 'Writer', name: 'C. Hale' },
          { role: 'Penciller', name: 'R. Vance' },
        ],
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Tidewrack Survey');
    const line = screen.getByTestId('calendar-creators-6003');
    expect(line).toHaveTextContent('A. Marlowe · B. Osgood · R. Vance');
    // Third writer cut, and a role the browse line does not carry stays off it.
    expect(line).not.toHaveTextContent('C. Hale');
    expect(line).not.toHaveTextContent('D. Quill');
  });

  it('FRG-UI-042 — an entry storing no creators and no description omits both lines rather than reserving them', async () => {
    const records = [
      makePullEntry({
        id: 6004,
        seriesName: 'Hollow Signal',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Hollow Signal');
    expect(screen.queryByTestId('calendar-creators-6004')).not.toBeInTheDocument();
    expect(screen.queryByTestId('calendar-deck-6004')).not.toBeInTheDocument();
    // The publisher chip is not enrichment — it renders for every entry.
    expect(screen.getByTestId('calendar-publisher-6004')).toBeInTheDocument();
  });

  it('FRG-UI-042 — the row description is stripped of markup and clamped to two lines', async () => {
    // A maximal (backend-capped 4000-char) description must not push the row
    // past its rhythm, and the untrusted ComicVine deck never reaches the DOM
    // as markup.
    const records = [
      makePullEntry({
        id: 6005,
        seriesName: 'Marrow Line',
        releaseDate: '2026-07-01',
        matchType: 'unmatched',
        description: '<b>x</b>' + ' filler word'.repeat(200),
      }),
    ];
    const { fetcher } = fakeFetcher(() => pageOf(records, { pageSize: 200 }));
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Marrow Line');
    const deck = screen.getByTestId('calendar-deck-6005');
    expect(deck.innerHTML).not.toContain('<b>');
    expect(deck.textContent?.startsWith('x filler word')).toBe(true);
    expect(deck.className).toMatch(/rowDeck/);
    // The full text stays on the detail surface — the row carries a teaser.
    expect(
      screen.getByRole('button', { name: 'Show details for Marrow Line' }),
    ).toBeInTheDocument();
  });
});

describe('FRG-PULL-007: search completion re-projects the week', () => {
  it('FRG-PULL-007 — a search command reaching completed refetches the pull week', async () => {
    const week = '2026-W27';
    const records = [makeLinkedPullEntry('Saga', { releaseDate: '2026-07-01' })];
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
      makeLinkedPullEntry('Saga', { releaseDate: '2026-07-01', publisher: 'Image' }),
      makeLinkedPullEntry('Batman', {
        releaseDate: '2026-07-01',
        publisher: 'DC',
        matchedIssueId: 501,
        series: { id: 8, title: 'Batman' },
      }),
      // An unmatched Image row so the Following banner shows a nonzero "more".
      makePullEntry({
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
    // named in the banner too —
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
    const records = [makeLinkedPullEntry('Saga', { releaseDate: futureDay })];
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

/**
 * FRG-UI-045 — a read-only series' issue is excluded from the linked pull
 * projection upstream, so the Calendar offers it no want/skip or search. This
 * is the defence-in-depth half: whatever reaches the screen, a refused write
 * must state its reason rather than read as a toggle that did not stick.
 */
describe('FRG-UI-045: Calendar refusals are visible', () => {
  it('FRG-UI-045 — a refused want/skip toggle surfaces the reason', async () => {
    const records = [
      makeLinkedPullEntry('Example Series', {
        releaseDate: '2026-07-01',
        state: 'unmonitored',
        matchedIssueId: 500,
      }),
    ];
    const { fetcher } = fakeFetcher((path, init) => {
      if (init?.method === 'PUT' && path === '/api/v1/issues/500') {
        throw new Error('series is in a read-only library');
      }
      return pageOf(records, { pageSize: 200 });
    });
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Example Series');
    await user.click(screen.getByRole('button', { name: 'Monitor Example Series' }));

    expect(await screen.findByTestId('calendar-action-error')).toHaveTextContent(
      'series is in a read-only library',
    );
  });

  it('FRG-UI-045 — a refused search dispatch surfaces the reason', async () => {
    const records = [
      makeLinkedPullEntry('Example Series', { releaseDate: '2026-07-01' }),
    ];
    const { fetcher } = fakeFetcher((path, init) => {
      if (init?.method === 'POST' && path === '/api/v1/command') {
        throw new Error('series is in a read-only library');
      }
      return pageOf(records, { pageSize: 200 });
    });
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Example Series');
    await user.click(screen.getByRole('button', { name: 'Search for Example Series' }));

    expect(await screen.findByTestId('calendar-action-error')).toHaveTextContent(
      'series is in a read-only library',
    );
  });

  it('FRG-UI-045 — an accepted want/skip leaves no error region behind', async () => {
    // The projection honours the write here, so the refetch that settles the
    // toggle must serve the re-projected (monitored) state — leaving the
    // record unmonitored would legitimately trigger the refusal explanation.
    let monitored = false;
    const { spy, fetcher } = fakeFetcher((path, init) => {
      if (init?.method === 'PUT' && path === '/api/v1/issues/500') {
        monitored = true;
        return makeIssue({ id: 500, series_id: 7, monitored: true });
      }
      return pageOf(
        [
          makeLinkedPullEntry('Example Series', {
            releaseDate: '2026-07-01',
            state: monitored ? 'missing_wanted' : 'unmonitored',
            matchedIssueId: 500,
          }),
        ],
        { pageSize: 200 },
      );
    });
    const user = userEvent.setup();
    renderWithProviders(<CalendarScreen />, { fetcher, route: '/calendar?week=2026-W27' });

    await screen.findByText('Example Series');
    await user.click(screen.getByRole('button', { name: 'Monitor Example Series' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/issues/500', {
        method: 'PUT',
        body: { monitored: true },
      }),
    );
    expect(screen.queryByTestId('calendar-action-error')).not.toBeInTheDocument();
  });
});
