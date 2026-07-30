import { describe, it, expect } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { makeIssue, makeSeriesResource, pageOf } from '../../test/mockData';
import { setViewportWidth } from '../../test/viewport';
import { createQueryClient } from '../../queryClient';
import { queryKeys } from '../../api/queryKeys';
import type { PullEntryRecord } from '../../api/types';
import { COMPACT_CROSSOVER_PX } from '../../theme/layout';
import { CalendarScreen } from './CalendarScreen';

/**
 * FRG-UI-018 / FRG-UI-047 / FRG-UI-048 — the Calendar at real-library density:
 * two entry presentations either side of one crossover, status indicators that
 * are not shaped or announced as controls, and a monitor toggle that
 * acknowledges activation instead of looking dead until a refetch lands.
 */

const WEEK = '2026-W27';
const DAY = '2026-07-01';
const WIDE = COMPACT_CROSSOVER_PX + 100;
const NARROW = COMPACT_CROSSOVER_PX - 300;

/** Long enough to have shattered mid-word in the shipped clamped card grid. */
const LONG_TITLE = 'Chronicles of the Meridian Expedition Deluxe Omnibus';

function makePullRecord(
  overrides: Partial<PullEntryRecord> & Pick<PullEntryRecord, 'seriesName'>,
): PullEntryRecord {
  return {
    id: null,
    week: WEEK,
    publisher: 'Umbral Press',
    issueNumber: '1',
    releaseDate: DAY,
    cvSeriesId: null,
    cvIssueId: null,
    matchType: null,
    matchedIssueId: null,
    state: null,
    series: null,
    issue: null,
    coverUrl: null,
    description: null,
    upc: null,
    creators: [],
    characters: [],
    ...overrides,
  };
}

/** A linked library entry: the only shape that carries a real monitor toggle. */
function linkedRow(
  name: string,
  over: Partial<PullEntryRecord> = {},
): PullEntryRecord {
  return makePullRecord({
    seriesName: name,
    matchType: 'id',
    matchedIssueId: 500,
    state: 'missing_wanted',
    series: { id: 7, title: name },
    issue: { id: 500, issueNumber: '1', title: null },
    ...over,
  });
}

function renderWeek(
  records: PullEntryRecord[],
  resolver?: Parameters<typeof fakeFetcher>[0],
) {
  const { spy, fetcher } = fakeFetcher(
    resolver ??
      ((path) =>
        path.startsWith('/api/v1/series')
          ? pageOf([])
          : pageOf(records, { pageSize: 200 })),
  );
  const rendered = renderWithProviders(<CalendarScreen />, {
    fetcher,
    route: `/calendar?week=${WEEK}`,
  });
  return { spy, ...rendered };
}

/** Every action an entry exposes, identified by its accessible name. */
function actionNames(card: HTMLElement): string[] {
  return within(card)
    .queryAllByRole('button')
    .map((b) => b.getAttribute('aria-label') ?? '')
    .sort();
}

/** The monitor toggle's bookmark path — the glyph FRG-UI-047 confines to it. */
const BOOKMARK_PATH = 'M6 3h12v18l-6-4.5L6 21z';

function bookmarkGlyphCount(root: HTMLElement): number {
  return root.querySelectorAll(`svg path[d="${BOOKMARK_PATH}"]`).length;
}

describe('FRG-UI-018: responsive entry presentation', () => {
  it('FRG-UI-018 — at or above the crossover an entry is an agenda row whose long title is neither clamped nor truncated', async () => {
    setViewportWidth(WIDE);
    renderWeek([makePullRecord({ id: 1, seriesName: LONG_TITLE, matchType: 'unmatched' })]);

    const card = await screen.findByTestId('calendar-card-1');
    expect(card).toHaveAttribute('data-mode', 'row');
    // The whole title is in one element: no clamp dropped characters and no
    // ellipsis stood in for them.
    const title = within(card).getByText(LONG_TITLE);
    expect(title.textContent).toBe(LONG_TITLE);
    expect(title.className).not.toMatch(/clamp/i);
    // No action on the row renders a text label that would eat the measure.
    for (const button of within(card).getAllByRole('button')) {
      expect(button.textContent).toBe('');
    }
  });

  it('FRG-UI-018 — below the crossover an entry is a card with every action icon-only on a rail beneath the title block', async () => {
    setViewportWidth(NARROW);
    renderWeek([
      makePullRecord({
        id: 1,
        seriesName: LONG_TITLE,
        matchType: 'unmatched',
        description: 'A survey ship logs a coastline that was not there before.',
      }),
    ]);

    const card = await screen.findByTestId('calendar-card-1');
    expect(card).toHaveAttribute('data-mode', 'card');
    // Two children with the detail closed: the title block, then the rail — the
    // rail is BENEATH the title, never beside it.
    expect(card.children).toHaveLength(2);
    const rail = card.children[1] as HTMLElement;
    const add = screen.getByRole('button', { name: `Add ${LONG_TITLE}` });
    expect(rail).toContainElement(add);
    expect(within(rail).getAllByRole('button').length).toBeGreaterThan(1);
    for (const button of within(rail).getAllByRole('button')) {
      expect(button.textContent).toBe('');
    }
    expect(within(card).getByText(LONG_TITLE).textContent).toBe(LONG_TITLE);
  });

  it('FRG-UI-018 — neither mode hides an action the other offers', async () => {
    const records = [
      linkedRow('Meridian Signal', {
        id: 1,
        description: 'A relay station answers on a dead channel.',
      }),
      makePullRecord({ id: 2, seriesName: 'Tidewrack Survey', matchType: 'unmatched' }),
    ];

    setViewportWidth(WIDE);
    const wide = renderWeek(records);
    await screen.findByTestId('calendar-card-1');
    const wideActions = [
      actionNames(screen.getByTestId('calendar-card-1')),
      actionNames(screen.getByTestId('calendar-card-2')),
    ];
    // Sanity: the fixture actually exposes actions, so an empty-vs-empty
    // comparison cannot pass this test vacuously.
    expect(wideActions[0].length).toBeGreaterThan(0);
    wide.unmount();

    setViewportWidth(NARROW);
    renderWeek(records);
    await screen.findByTestId('calendar-card-1');
    expect([
      actionNames(screen.getByTestId('calendar-card-1')),
      actionNames(screen.getByTestId('calendar-card-2')),
    ]).toEqual(wideActions);
  });

  it('FRG-UI-018 — the day gutter folds into an inline day header only below the crossover', async () => {
    setViewportWidth(NARROW);
    const narrow = renderWeek([
      makePullRecord({ id: 1, seriesName: 'Tidewrack Survey', matchType: 'unmatched' }),
    ]);
    expect(await screen.findByTestId(`calendar-day-inline-${DAY}`)).toBeInTheDocument();
    narrow.unmount();

    setViewportWidth(WIDE);
    renderWeek([
      makePullRecord({ id: 1, seriesName: 'Tidewrack Survey', matchType: 'unmatched' }),
    ]);
    await screen.findByTestId('calendar-card-1');
    expect(screen.queryByTestId(`calendar-day-inline-${DAY}`)).not.toBeInTheDocument();
  });

  it('FRG-UI-018 — a resize across the crossover switches presentation without a remount of the week', async () => {
    setViewportWidth(WIDE);
    renderWeek([
      makePullRecord({ id: 1, seriesName: 'Tidewrack Survey', matchType: 'unmatched' }),
    ]);
    expect(await screen.findByTestId('calendar-card-1')).toHaveAttribute(
      'data-mode',
      'row',
    );

    act(() => setViewportWidth(NARROW));
    await waitFor(() =>
      expect(screen.getByTestId('calendar-card-1')).toHaveAttribute(
        'data-mode',
        'card',
      ),
    );
  });
});

describe('FRG-UI-047: status indicators are never shaped like controls', () => {
  const unlinkedStates: [string, Partial<PullEntryRecord>][] = [
    ['unmatched', { matchType: 'unmatched', state: null }],
    ['a new-series debut', { matchType: 'new_series', state: null }],
    [
      'pending refresh',
      { matchType: 'id', state: 'pending_refresh', series: { id: 7, title: 'Tidewrack Survey' } },
    ],
  ];

  for (const [label, over] of unlinkedStates) {
    it(`FRG-UI-047 — an entry with no real toggle (${label}) shows a status, not a button`, async () => {
      setViewportWidth(WIDE);
      renderWeek([makePullRecord({ id: 1, seriesName: 'Tidewrack Survey', ...over })]);

      const card = await screen.findByTestId('calendar-card-1');
      const chip = within(card).getByTestId('calendar-state-1');
      // Semantically a status: no control role, no pressed state, and its
      // meaning is the text inside it.
      expect(chip.tagName).toBe('SPAN');
      expect(chip).not.toHaveAttribute('role');
      expect(chip).not.toHaveAttribute('aria-pressed');
      expect(chip).not.toHaveAttribute('tabindex');
      expect(chip.tabIndex).toBe(-1);
      expect(chip.textContent).toBeTruthy();
      // No want/skip button anywhere on the entry, and no bookmark glyph —
      // filled or hollow — impersonating one.
      expect(
        within(card).queryByRole('button', { name: /^(Want|Skip) / }),
      ).not.toBeInTheDocument();
      expect(bookmarkGlyphCount(card)).toBe(0);
    });
  }

  it('FRG-UI-047 — an unlinked entry with no actions at all exposes no button and no glyph', async () => {
    // Series already in the library, no stored enrichment: nothing this entry
    // offers is actionable, so the card must contain zero controls.
    const client = createQueryClient();
    client.setQueryData(queryKeys.series.all(), [
      makeSeriesResource({ id: 7, title: 'tidewrack survey' }),
    ]);
    const { fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/series')
        ? pageOf([makeSeriesResource({ id: 7, title: 'tidewrack survey' })])
        : pageOf(
            [
              makePullRecord({
                id: 1,
                seriesName: 'Tidewrack Survey',
                matchType: 'unmatched',
              }),
            ],
            { pageSize: 200 },
          ),
    );
    setViewportWidth(WIDE);
    renderWithProviders(<CalendarScreen />, {
      client,
      fetcher,
      route: `/calendar?week=${WEEK}`,
    });

    const card = await screen.findByTestId('calendar-card-1');
    expect(within(card).queryAllByRole('button')).toHaveLength(0);
    expect(card.querySelectorAll('svg')).toHaveLength(0);
    expect(within(card).getByTestId('calendar-state-1')).toHaveTextContent(
      'Not in library',
    );
  });

  it('FRG-UI-047 — a linked entry carries a real aria-pressed toggle and it alone draws the bookmark', async () => {
    setViewportWidth(WIDE);
    renderWeek([linkedRow('Meridian Signal', { id: 1 })]);

    const card = await screen.findByTestId('calendar-card-1');
    const toggle = within(card).getByRole('button', { name: 'Skip Meridian Signal' });
    expect(toggle.tagName).toBe('BUTTON');
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(toggle).not.toBeDisabled();
    // Exactly one bookmark on the entry, and it is inside the toggle.
    expect(bookmarkGlyphCount(card)).toBe(1);
    expect(bookmarkGlyphCount(toggle)).toBe(1);
  });

  it('FRG-UI-047 — the per-entry button count equals the number of actions that entry has', async () => {
    setViewportWidth(WIDE);
    renderWeek([
      // Linked + enriched: details, monitor, search.
      linkedRow('Meridian Signal', {
        id: 1,
        description: 'A relay station answers on a dead channel.',
      }),
      // Unlinked, addable, no enrichment: add alone.
      makePullRecord({ id: 2, seriesName: 'Tidewrack Survey', matchType: 'unmatched' }),
    ]);

    await screen.findByTestId('calendar-card-1');
    expect(actionNames(screen.getByTestId('calendar-card-1'))).toEqual([
      'Search for Meridian Signal',
      'Show details for Meridian Signal',
      'Skip Meridian Signal',
    ]);
    expect(actionNames(screen.getByTestId('calendar-card-2'))).toEqual([
      'Add Tidewrack Survey',
    ]);
  });
});

describe('FRG-UI-048: in-flight feedback for the monitor toggle', () => {
  /** A PUT that stays pending until the test releases it. */
  function deferredToggle(records: PullEntryRecord[]) {
    let release: (() => void) | null = null;
    let fail: ((error: Error) => void) | null = null;
    const resolver = (path: string, init?: { method?: string }) => {
      if (init?.method === 'PUT' && path === '/api/v1/issues/500') {
        return new Promise((resolve, reject) => {
          release = () => resolve(makeIssue({ id: 500, series_id: 7, monitored: false }));
          fail = (error: Error) => reject(error);
        });
      }
      if (path.startsWith('/api/v1/series')) return pageOf([]);
      return pageOf(records, { pageSize: 200 });
    };
    return {
      resolver,
      release: () => release?.(),
      fail: (message: string) => fail?.(new Error(message)),
    };
  }

  it('FRG-UI-048 — activation renders the requested state at once in a busy presentation and a second activation issues no second mutation', async () => {
    const records = [linkedRow('Meridian Signal', { id: 1 })];
    const deferred = deferredToggle(records);
    setViewportWidth(WIDE);
    const { spy } = renderWeek(records, deferred.resolver);
    const user = userEvent.setup();

    await screen.findByTestId('calendar-card-1');
    await user.click(screen.getByRole('button', { name: 'Skip Meridian Signal' }));

    // The requested state (unmonitored) is on screen before the PUT settles,
    // and the control says it is working.
    const busy = await screen.findByRole('button', { name: 'Want Meridian Signal' });
    expect(busy).toHaveAttribute('aria-pressed', 'false');
    expect(busy).toHaveAttribute('aria-busy', 'true');

    const putsBefore = spy.mock.calls.filter(([, init]) => init?.method === 'PUT').length;
    expect(putsBefore).toBe(1);
    await user.click(busy);
    expect(spy.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1);

    deferred.release();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Skip Meridian Signal' })).toHaveAttribute(
        'aria-busy',
        'false',
      ),
    );
  });

  it('FRG-UI-048 — success settles to the re-projected derived state, not the optimistic guess', async () => {
    // The projection keeps reporting `missing_wanted` after the PUT succeeds:
    // the entry must end up showing the SERVER's state, not the requested one.
    const records = [linkedRow('Meridian Signal', { id: 1 })];
    const { spy } = renderWeek(records, (path, init) => {
      if (init?.method === 'PUT' && path === '/api/v1/issues/500') {
        return makeIssue({ id: 500, series_id: 7, monitored: false });
      }
      if (path.startsWith('/api/v1/series')) return pageOf([]);
      return pageOf(records, { pageSize: 200 });
    });
    const user = userEvent.setup();

    await screen.findByTestId('calendar-card-1');
    await user.click(screen.getByRole('button', { name: 'Skip Meridian Signal' }));

    await waitFor(() =>
      expect(spy.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1),
    );
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Skip Meridian Signal' }),
      ).toHaveAttribute('aria-pressed', 'true'),
    );
    expect(screen.queryByTestId('calendar-action-error')).not.toBeInTheDocument();
  });

  it('FRG-UI-048 — a failed toggle reverts to the true state and surfaces the failure', async () => {
    const records = [linkedRow('Meridian Signal', { id: 1 })];
    const deferred = deferredToggle(records);
    renderWeek(records, deferred.resolver);
    const user = userEvent.setup();

    await screen.findByTestId('calendar-card-1');
    await user.click(screen.getByRole('button', { name: 'Skip Meridian Signal' }));
    await screen.findByRole('button', { name: 'Want Meridian Signal' });

    deferred.fail('That series is read-only.');

    // Back to the entry's true state, AND the operator is told why — never a
    // silent snap-back that reads as a click that did nothing.
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Skip Meridian Signal' }),
      ).toHaveAttribute('aria-pressed', 'true'),
    );
    const alert = await screen.findByTestId('calendar-action-error');
    expect(alert).toHaveTextContent('That series is read-only.');
    expect(alert).toHaveAttribute('role', 'alert');
  });
});
