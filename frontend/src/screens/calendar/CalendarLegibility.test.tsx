import { describe, it, expect } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  PULL_DAY,
  PULL_WEEK,
  makeCommand,
  makeIssue,
  makeLinkedPullEntry,
  makePullEntry,
  makeSeriesResource,
  pageOf,
} from '../../test/mockData';
import { addWeeks, currentIsoWeek, isoDateKey, weekDates } from '../../utils/isoWeek';
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

const WIDE = COMPACT_CROSSOVER_PX + 100;
const NARROW = COMPACT_CROSSOVER_PX - 300;

/** A week that is always ahead of the store date, whenever the suite runs. */
const FUTURE_WEEK = addWeeks(currentIsoWeek(), 4);
const FUTURE_DAY = isoDateKey(weekDates(FUTURE_WEEK)[2]);

/** Long enough to have shattered mid-word in the shipped clamped card grid. */
const LONG_TITLE = 'Chronicles of the Meridian Expedition Deluxe Omnibus';

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
    route: `/calendar?week=${PULL_WEEK}`,
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

/**
 * The subtree's text as assistive technology receives it: everything hidden from
 * the accessibility tree removed. `textContent` alone cannot tell a date drawn
 * twice from a date drawn once and mirrored decoratively.
 */
function accessibleText(root: HTMLElement): string {
  const clone = root.cloneNode(true) as HTMLElement;
  for (const hidden of Array.from(clone.querySelectorAll('[aria-hidden="true"]'))) {
    hidden.remove();
  }
  return clone.textContent ?? '';
}

describe('FRG-UI-018: responsive entry presentation', () => {
  it('FRG-UI-018 — at or above the crossover an entry is an agenda row whose long title is neither clamped nor truncated', async () => {
    setViewportWidth(WIDE);
    renderWeek([makePullEntry({ id: 1, seriesName: LONG_TITLE, matchType: 'unmatched' })]);

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
      makePullEntry({
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
      makeLinkedPullEntry('Meridian Signal', {
        id: 1,
        description: 'A relay station answers on a dead channel.',
      }),
      makePullEntry({ id: 2, seriesName: 'Tidewrack Survey', matchType: 'unmatched' }),
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
      makePullEntry({ id: 1, seriesName: 'Tidewrack Survey', matchType: 'unmatched' }),
    ]);
    expect(await screen.findByTestId(`calendar-day-inline-${PULL_DAY}`)).toBeInTheDocument();
    narrow.unmount();

    setViewportWidth(WIDE);
    renderWeek([
      makePullEntry({ id: 1, seriesName: 'Tidewrack Survey', matchType: 'unmatched' }),
    ]);
    await screen.findByTestId('calendar-card-1');
    expect(screen.queryByTestId(`calendar-day-inline-${PULL_DAY}`)).not.toBeInTheDocument();
  });

  it('FRG-UI-018 — a future-dated day is marked not-yet-released once in its heading, never per entry', async () => {
    // Per entry the marking is a ~110px nowrap token in the row's meta track,
    // and the title's measure is what pays for it — while the store date that
    // makes an entry unreleased belongs to the whole day group anyway.
    setViewportWidth(WIDE);
    const records = [
      makePullEntry({
        id: 1,
        seriesName: 'Tidewrack Survey',
        matchType: 'unmatched',
        week: FUTURE_WEEK,
        releaseDate: FUTURE_DAY,
      }),
      makePullEntry({
        id: 2,
        seriesName: 'Meridian Signal',
        matchType: 'unmatched',
        week: FUTURE_WEEK,
        releaseDate: FUTURE_DAY,
      }),
    ];
    const { fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/series')
        ? pageOf([])
        : pageOf(records, { pageSize: 200 }),
    );
    renderWithProviders(<CalendarScreen />, {
      fetcher,
      route: `/calendar?week=${FUTURE_WEEK}`,
    });

    const day = await screen.findByTestId(`calendar-day-${FUTURE_DAY}`);
    expect(screen.getAllByText('Not yet released')).toHaveLength(1);
    expect(
      within(day).getByTestId(`calendar-unreleased-${FUTURE_DAY}`),
    ).toBeInTheDocument();
    // Both entries carry the state as data, and neither repeats the words.
    for (const id of [1, 2]) {
      const card = screen.getByTestId(`calendar-card-${id}`);
      expect(card).toHaveAttribute('data-future', 'true');
      expect(within(card).queryByText('Not yet released')).not.toBeInTheDocument();
    }
  });

  it('FRG-UI-018 — each day group is a heading over a list of entries in both modes', async () => {
    // 60 entries with no structure is 240 tab stops and no jump points; the
    // grouping the sighted reader gets from the gutter has to exist in the
    // markup too.
    for (const width of [WIDE, NARROW]) {
      setViewportWidth(width);
      const view = renderWeek([
        makeLinkedPullEntry('Meridian Signal', { id: 1 }),
        makePullEntry({ id: 2, seriesName: 'Tidewrack Survey', matchType: 'unmatched' }),
      ]);
      const day = await screen.findByTestId(`calendar-day-${PULL_DAY}`);
      const heading = within(day).getByRole('heading', { level: 2 });
      // The date is in the accessible name at both widths, though only the
      // narrow mode draws it inside the heading.
      expect(heading).toHaveAccessibleName(expect.stringContaining('Jul'));
      // And exactly once in the whole group: the wide gutter draws the same date
      // beside the heading, so an unhidden gutter has assistive technology read
      // every date in the week twice.
      expect(accessibleText(day).match(/Jul/g) ?? []).toHaveLength(1);
      const list = within(day).getByRole('list');
      expect(within(list).getAllByRole('listitem')).toHaveLength(2);
      expect(list).toContainElement(screen.getByTestId('calendar-card-1'));
      view.unmount();
    }
  });

  it('FRG-UI-018 — a resize across the crossover switches presentation without a remount of the week', async () => {
    setViewportWidth(WIDE);
    renderWeek([
      makePullEntry({ id: 1, seriesName: 'Tidewrack Survey', matchType: 'unmatched' }),
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
      renderWeek([makePullEntry({ id: 1, seriesName: 'Tidewrack Survey', ...over })]);

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
      // No monitor button anywhere on the entry, and no bookmark glyph —
      // filled or hollow — impersonating one.
      expect(
        within(card).queryByRole('button', { name: /^Monitor / }),
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
              makePullEntry({
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
      route: `/calendar?week=${PULL_WEEK}`,
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
    renderWeek([makeLinkedPullEntry('Meridian Signal', { id: 1 })]);

    const card = await screen.findByTestId('calendar-card-1');
    const toggle = within(card).getByRole('button', { name: 'Monitor Meridian Signal' });
    expect(toggle.tagName).toBe('BUTTON');
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(toggle).not.toBeDisabled();
    // Exactly one bookmark on the entry, and it is inside the toggle.
    expect(bookmarkGlyphCount(card)).toBe(1);
    expect(bookmarkGlyphCount(toggle)).toBe(1);
  });

  it('FRG-UI-047 — a linked entry in a non-wanted derived state still carries the real toggle beside its status', async () => {
    // Whether the entry is monitored is not the same question as whether it is
    // wanted: a downloading issue is monitored and stays operable, so the derived
    // state must decide the CHIP's words and never whether a control exists.
    setViewportWidth(WIDE);
    renderWeek([makeLinkedPullEntry('Meridian Signal', { id: 1, state: 'downloading' })]);

    const card = await screen.findByTestId('calendar-card-1');
    expect(within(card).getByTestId('calendar-state-1')).toHaveTextContent(
      'Downloading',
    );
    const toggle = within(card).getByRole('button', { name: 'Monitor Meridian Signal' });
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(toggle).toHaveAttribute('aria-busy', 'false');
    expect(bookmarkGlyphCount(card)).toBe(1);
    expect(bookmarkGlyphCount(toggle)).toBe(1);
  });

  it('FRG-UI-047 — the toggle names itself neutrally in both states so aria-pressed is not contradicted', async () => {
    // An action-phrased name ("Skip …") beside aria-pressed=true announces
    // "skipping is ON" — the negation of the truth — so the name must carry no
    // verb at all and the state must live only on aria-pressed.
    setViewportWidth(WIDE);
    renderWeek([
      makeLinkedPullEntry('Meridian Signal', { id: 1 }),
      makeLinkedPullEntry('Tidewrack Survey', {
        id: 2,
        matchedIssueId: 501,
        state: 'unmonitored',
        series: { id: 8, title: 'Tidewrack Survey' },
      }),
    ]);

    await screen.findByTestId('calendar-card-1');
    const monitored = screen.getByRole('button', { name: 'Monitor Meridian Signal' });
    const notMonitored = screen.getByRole('button', { name: 'Monitor Tidewrack Survey' });
    expect(monitored).toHaveAttribute('aria-pressed', 'true');
    expect(notMonitored).toHaveAttribute('aria-pressed', 'false');
    for (const toggle of [monitored, notMonitored]) {
      expect(toggle.getAttribute('aria-label')).not.toMatch(/skip|want|stop/i);
    }
  });

  it('FRG-UI-047 — the per-entry button count equals the number of actions that entry has', async () => {
    setViewportWidth(WIDE);
    renderWeek([
      // Linked + enriched: details, monitor, search.
      makeLinkedPullEntry('Meridian Signal', {
        id: 1,
        description: 'A relay station answers on a dead channel.',
      }),
      // Unlinked, addable, no enrichment: add alone.
      makePullEntry({ id: 2, seriesName: 'Tidewrack Survey', matchType: 'unmatched' }),
    ]);

    await screen.findByTestId('calendar-card-1');
    expect(actionNames(screen.getByTestId('calendar-card-1'))).toEqual([
      'Monitor Meridian Signal',
      'Search for Meridian Signal',
      'Show details for Meridian Signal',
    ]);
    expect(actionNames(screen.getByTestId('calendar-card-2'))).toEqual([
      'Add Tidewrack Survey',
    ]);
  });
});

describe('FRG-UI-047: a control that is present is a real, honest control', () => {
  it('FRG-UI-047 — the details control references the panel it opens, and only while it exists', async () => {
    setViewportWidth(WIDE);
    renderWeek([
      makeLinkedPullEntry('Meridian Signal', {
        id: 1,
        description: 'A relay station answers on a dead channel.',
      }),
    ]);
    const user = userEvent.setup();

    await screen.findByTestId('calendar-card-1');
    const trigger = screen.getByRole('button', {
      name: 'Show details for Meridian Signal',
    });
    // Closed: no reference at all rather than one pointing at nothing.
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).not.toHaveAttribute('aria-controls');

    await user.click(trigger);
    const opened = screen.getByRole('button', {
      name: 'Hide details for Meridian Signal',
    });
    const panelId = opened.getAttribute('aria-controls');
    expect(panelId).toBe('calendar-detail-1');
    expect(document.getElementById(panelId as string)).toBeInTheDocument();
  });

  it('FRG-UI-047 — a running search keeps its control in keyboard order and announces itself', async () => {
    // `disabled` on the focused button drops focus to the document body and
    // silently disables every row's search at once, because the running flag is
    // screen-wide; unavailable-but-focusable plus a live status region does not.
    const records = [
      makeLinkedPullEntry('Meridian Signal', { id: 1 }),
      makeLinkedPullEntry('Tidewrack Survey', {
        id: 2,
        matchedIssueId: 501,
        series: { id: 8, title: 'Tidewrack Survey' },
      }),
    ];
    setViewportWidth(WIDE);
    renderWeek(records, (path, init) => {
      if (init?.method === 'POST' && path === '/api/v1/command') {
        return makeCommand({ id: 90, name: 'issue-search', status: 'queued' });
      }
      if (path === '/api/v1/command/90') {
        return makeCommand({ id: 90, name: 'issue-search', status: 'started' });
      }
      if (path.startsWith('/api/v1/series')) return pageOf([]);
      return pageOf(records, { pageSize: 200 });
    });
    const user = userEvent.setup();

    await screen.findByTestId('calendar-card-1');
    const search = screen.getByRole('button', { name: 'Search for Meridian Signal' });
    await user.click(search);

    const status = await screen.findByTestId('command-status');
    expect(status).toHaveAttribute('role', 'status');
    for (const name of ['Meridian Signal', 'Tidewrack Survey']) {
      const button = screen.getByRole('button', { name: `Search for ${name}` });
      expect(button).toHaveAttribute('aria-disabled', 'true');
      expect(button).not.toBeDisabled();
    }
    // The control the operator activated still holds focus.
    expect(search).toHaveFocus();
  });
});

describe('FRG-UI-048: in-flight feedback for the monitor toggle', () => {
  /**
   * A fetcher whose PUTs AND whose post-mutation pull refetch stay pending until
   * the test releases them, one issue id at a time. Nothing may resolve in a
   * microtask: a fetcher that settles immediately hides both the window in which
   * an optimistic value can flash back to the stale projection and the ordering
   * that decides whether a concurrent toggle ever settles at all.
   */
  function gatedFetcher(
    records: PullEntryRecord[],
    settled?: PullEntryRecord[],
    { holdRefetches = false } = {},
  ) {
    const puts = new Map<
      number,
      { resolve: () => void; reject: (error: Error) => void }
    >();
    const refetches: Array<() => void> = [];
    let pullCalls = 0;
    const resolver = (path: string, init?: { method?: string }) => {
      const put = /^\/api\/v1\/issues\/(\d+)$/.exec(path);
      if (init?.method === 'PUT' && put) {
        const issueId = Number(put[1]);
        return new Promise((resolve, reject) => {
          puts.set(issueId, {
            resolve: () =>
              resolve(makeIssue({ id: issueId, series_id: 7, monitored: false })),
            reject,
          });
        });
      }
      if (path.startsWith('/api/v1/series')) return pageOf([]);
      pullCalls += 1;
      // The first load resolves so the week renders. A refetch after it lands a
      // macrotask later at the earliest — or only when the test releases it,
      // which is the window an optimistic value has to survive.
      if (pullCalls === 1) return pageOf(records, { pageSize: 200 });
      return new Promise((resolve) => {
        const land = () => resolve(pageOf(settled ?? records, { pageSize: 200 }));
        if (holdRefetches) refetches.push(land);
        else setTimeout(land, 0);
      });
    };
    return {
      resolver,
      release: (issueId: number) => act(() => void puts.get(issueId)?.resolve()),
      fail: (issueId: number, message: string) =>
        act(() => void puts.get(issueId)?.reject(new Error(message))),
      pendingRefetches: () => refetches.length,
      releaseRefetches: () =>
        act(() => {
          for (const release of refetches.splice(0)) release();
        }),
    };
  }

  const toggleOf = (name: string) =>
    screen.getByRole('button', { name: `Monitor ${name}` });

  it('FRG-UI-048 — activation renders the requested state at once in a busy presentation and a second activation issues no second mutation', async () => {
    const records = [makeLinkedPullEntry('Meridian Signal', { id: 1 })];
    const gated = gatedFetcher(records);
    setViewportWidth(WIDE);
    const { spy } = renderWeek(records, gated.resolver);
    const user = userEvent.setup();

    await screen.findByTestId('calendar-card-1');
    await user.click(toggleOf('Meridian Signal'));

    // The requested state (unmonitored) is on screen before the PUT settles,
    // and the control says it is unavailable while it works.
    const busy = toggleOf('Meridian Signal');
    expect(busy).toHaveAttribute('aria-pressed', 'false');
    expect(busy).toHaveAttribute('aria-disabled', 'true');
    // Unavailable AND working: without aria-busy the two are indistinguishable
    // to assistive technology, and a control that is merely unavailable reads as
    // one the operator cannot use rather than one that is mid-request.
    expect(busy).toHaveAttribute('aria-busy', 'true');

    expect(spy.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1);
    await user.click(busy);
    expect(spy.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1);

    gated.release(500);
    await waitFor(() =>
      expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-disabled', 'false'),
    );
    expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-busy', 'false');
  });

  it('FRG-UI-048 — the requested state holds across the whole refetch window rather than flashing back', async () => {
    // The cache still holds the pre-toggle page until the refetch lands, so
    // clearing the optimistic value when the PUT resolves would flip the
    // bookmark back to monitored for the length of that refetch — the "click
    // looks flaky" symptom this requirement exists to kill.
    const records = [makeLinkedPullEntry('Meridian Signal', { id: 1 })];
    const settled = [makeLinkedPullEntry('Meridian Signal', { id: 1, state: 'unmonitored' })];
    const gated = gatedFetcher(records, settled, { holdRefetches: true });
    setViewportWidth(WIDE);
    renderWeek(records, gated.resolver);
    const user = userEvent.setup();

    await screen.findByTestId('calendar-card-1');
    await user.click(toggleOf('Meridian Signal'));
    expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-pressed', 'false');

    gated.release(500);
    await waitFor(() => expect(gated.pendingRefetches()).toBe(1));
    // The refetch is in flight and the cache is still stale: the requested value
    // must be what is on screen, and the control must still read as busy.
    for (let tick = 0; tick < 5; tick += 1) {
      await act(async () => {
        await Promise.resolve();
      });
      expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-pressed', 'false');
      expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-disabled', 'true');
    }

    gated.releaseRefetches();
    // Settled on the SERVER's projection, and only then is the optimistic value
    // released — the value it lands on happens to agree, but it is no longer the
    // optimistic one that is holding it there.
    await waitFor(() =>
      expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-disabled', 'false'),
    );
    expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-pressed', 'false');
  });

  it('FRG-UI-048 — success settles to the re-projected derived state, not the optimistic guess', async () => {
    // The projection keeps reporting `missing_wanted` after the PUT succeeds:
    // the entry must end up showing the SERVER's state, not the requested one.
    const records = [makeLinkedPullEntry('Meridian Signal', { id: 1 })];
    const { spy } = renderWeek(records, (path, init) => {
      if (init?.method === 'PUT' && path === '/api/v1/issues/500') {
        return makeIssue({ id: 500, series_id: 7, monitored: false });
      }
      if (path.startsWith('/api/v1/series')) return pageOf([]);
      return pageOf(records, { pageSize: 200 });
    });
    const user = userEvent.setup();

    await screen.findByTestId('calendar-card-1');
    await user.click(toggleOf('Meridian Signal'));

    await waitFor(() =>
      expect(spy.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1),
    );
    await waitFor(() =>
      expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-pressed', 'true'),
    );
    expect(screen.queryByTestId('calendar-action-error')).not.toBeInTheDocument();
  });

  it('FRG-UI-048 — a toggle the projection does not honour is explained rather than silently reverted', async () => {
    // The derived state answers to the SERIES' monitored flag as well as the
    // issue's, so storing the issue flag on an issue whose series is unmonitored
    // answers 200 and leaves the entry exactly as it was. The bookmark reverting
    // with no message is indistinguishable from a click that did nothing.
    const records = [makeLinkedPullEntry('Meridian Signal', { id: 1, state: 'unmonitored' })];
    setViewportWidth(WIDE);
    const { spy } = renderWeek(records, (path, init) => {
      if (init?.method === 'PUT' && path === '/api/v1/issues/500') {
        return makeIssue({ id: 500, series_id: 7, monitored: true });
      }
      if (path.startsWith('/api/v1/series')) return pageOf([]);
      return pageOf(records, { pageSize: 200 });
    });
    const user = userEvent.setup();

    await screen.findByTestId('calendar-card-1');
    expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-pressed', 'false');
    await user.click(toggleOf('Meridian Signal'));

    await waitFor(() =>
      expect(spy.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1),
    );
    const alert = await screen.findByTestId('calendar-action-error');
    expect(alert).toHaveAttribute('role', 'alert');
    expect(alert).toHaveTextContent(/series is not monitored/i);
    // Settled on the projection and operable again, never left busy.
    await waitFor(() =>
      expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-disabled', 'false'),
    );
    expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-pressed', 'false');
    expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-busy', 'false');
  });

  it('FRG-UI-048 — two toggles in flight at once both settle, and neither is left permanently busy', async () => {
    // One mutation observer serves every row, so a second activation replaces
    // the first one's per-call callbacks: whatever clears the optimistic value
    // must belong to the activation itself, or the first row never recovers.
    const records = [
      makeLinkedPullEntry('Meridian Signal', { id: 1 }),
      makeLinkedPullEntry('Tidewrack Survey', {
        id: 2,
        matchedIssueId: 501,
        series: { id: 8, title: 'Tidewrack Survey' },
      }),
    ];
    const gated = gatedFetcher(records);
    setViewportWidth(WIDE);
    const { spy } = renderWeek(records, gated.resolver);
    const user = userEvent.setup();

    await screen.findByTestId('calendar-card-1');
    await user.click(toggleOf('Meridian Signal'));
    await user.click(toggleOf('Tidewrack Survey'));
    expect(spy.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(2);

    gated.release(501);
    gated.release(500);

    await waitFor(() => {
      expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-disabled', 'false');
      expect(toggleOf('Tidewrack Survey')).toHaveAttribute('aria-disabled', 'false');
    });
    // Both are operable again: a second activation reaches the server.
    await user.click(toggleOf('Meridian Signal'));
    expect(spy.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(3);
  });

  it('FRG-UI-048 — a failed toggle reverts to the true state and surfaces the failure even when another toggle succeeded meanwhile', async () => {
    const records = [
      makeLinkedPullEntry('Meridian Signal', { id: 1 }),
      makeLinkedPullEntry('Tidewrack Survey', {
        id: 2,
        matchedIssueId: 501,
        series: { id: 8, title: 'Tidewrack Survey' },
      }),
    ];
    const gated = gatedFetcher(records);
    setViewportWidth(WIDE);
    renderWeek(records, gated.resolver);
    const user = userEvent.setup();

    await screen.findByTestId('calendar-card-1');
    await user.click(toggleOf('Meridian Signal'));
    await user.click(toggleOf('Tidewrack Survey'));

    // The later mutation succeeds first; the shared observer's error would be
    // null by the time the earlier one is refused.
    gated.release(501);
    gated.fail(500, 'That series is read-only.');

    // Back to the entry's true state, AND the operator is told why — never a
    // silent snap-back that reads as a click that did nothing.
    await waitFor(() =>
      expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-pressed', 'true'),
    );
    const alert = await screen.findByTestId('calendar-action-error');
    expect(alert).toHaveTextContent('That series is read-only.');
    expect(alert).toHaveAttribute('role', 'alert');
    expect(toggleOf('Meridian Signal')).toHaveAttribute('aria-disabled', 'false');
  });
});
