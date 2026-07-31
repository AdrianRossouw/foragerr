import { describe, it, expect } from 'vitest';
import { screen, waitFor, act, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { ApiRequestError } from '../../api/fetcher';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  mockQueueEnvelope,
  mockQueuePage1,
  mockQueueRecord,
} from '../../test/mockData';
import { makeFakeSocketFactory } from '../../test/fakeSocket';
import { WebSocketBridge } from '../../ws/WebSocketBridge';
import { QueueScreen } from './QueueScreen';
import styles from './QueueScreen.module.css';
import queueCss from './QueueScreen.module.css?raw';

/**
 * FRG-UI-006 — Activity: queue screen. Rows render from the /api/v1/queue
 * paging envelope, live-update via the WebSocketBridge queue-progress patch
 * (fakeSocket-driven, no refetch), expose import_pending/import_blocked reason
 * popovers, remove via a dialog with delete-data + blocklist options (one row
 * or a whole selection), and page rather than cap at the first twenty.
 */
describe('FRG-UI-006: queue screen', () => {
  it('FRG-UI-006 — renders title, series/issue, status chip, progress, and size/remaining from the queue endpoint', async () => {
    const { spy, fetcher } = fakeFetcher(() => mockQueuePage1);
    renderWithProviders(<QueueScreen />, { fetcher });

    const row = await screen.findByTestId('queue-row-900');
    expect(spy).toHaveBeenCalledWith('/api/v1/queue?page=1');
    expect(within(row).getByText('Chapter Forty-One')).toBeInTheDocument(); // title
    expect(within(row).getByText('Saga')).toBeInTheDocument(); // series
    expect(within(row).getByText('#41')).toBeInTheDocument(); // issue
    expect(within(row).getByText('Downloading')).toBeInTheDocument(); // status chip
    // Progress derived from size/sizeleft: (100-90)/100 = 10%.
    expect(screen.getByTestId('queue-progress-900')).toHaveTextContent('10%');
    expect(within(row).getByText('90 B left of 100 B')).toBeInTheDocument();
    // Second record renders too.
    expect(screen.getByTestId('queue-progress-901')).toHaveTextContent('25%');
  });

  it('FRG-UI-006 — a WS progress message advances the row in place with no new /api/v1/queue fetch', async () => {
    const { spy, fetcher } = fakeFetcher(() => mockQueuePage1);
    const { factory, last } = makeFakeSocketFactory();
    renderWithProviders(
      <>
        <QueueScreen />
        <WebSocketBridge socketFactory={factory} />
      </>,
      { fetcher },
    );

    await screen.findByTestId('queue-row-900');
    expect(spy).toHaveBeenCalledTimes(1);

    act(() => last().emitOpen());
    act(() =>
      last().emitMessage({
        name: 'queue',
        action: 'progress',
        resource: { id: 900, page: 1, progress: 80, sizeLeft: 20 },
      }),
    );

    await waitFor(() =>
      expect(screen.getByTestId('queue-progress-900')).toHaveTextContent('80%'),
    );
    // Patched, not refetched.
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('FRG-UI-006 — an item patched to imported leaves the table without a reload', async () => {
    const { spy, fetcher } = fakeFetcher(() => mockQueuePage1);
    const { factory, last } = makeFakeSocketFactory();
    renderWithProviders(
      <>
        <QueueScreen />
        <WebSocketBridge socketFactory={factory} />
      </>,
      { fetcher },
    );

    await screen.findByTestId('queue-row-900');

    act(() => last().emitOpen());
    act(() =>
      last().emitMessage({
        name: 'queue',
        action: 'progress',
        resource: { id: 900, page: 1, progress: 100, sizeLeft: 0, status: 'imported' },
      }),
    );

    await waitFor(() =>
      expect(screen.queryByTestId('queue-row-900')).not.toBeInTheDocument(),
    );
    // The sibling row is untouched and no refetch happened.
    expect(screen.getByTestId('queue-row-901')).toBeInTheDocument();
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it.each([
    {
      state: 'import_pending',
      chipLabel: 'Awaiting import',
      messages: ['Waiting for the import pipeline'],
    },
    {
      state: 'import_blocked',
      chipLabel: 'Import blocked',
      messages: ['No files found are eligible for import', 'Unmapped remote path'],
    },
  ])(
    'FRG-UI-006 — a $state chip expands to a popover with the reason text',
    async ({ state, chipLabel, messages }) => {
      const envelope = mockQueueEnvelope([
        mockQueueRecord({ id: 910, state, status: 'warning', statusMessages: messages }),
      ]);
      const { fetcher } = fakeFetcher(() => envelope);
      const user = userEvent.setup();
      renderWithProviders(<QueueScreen />, { fetcher });

      const chip = await screen.findByRole('button', { name: chipLabel });
      // Reasons are hidden until the chip is activated.
      expect(screen.queryByText(messages[0])).not.toBeInTheDocument();

      await user.click(chip);
      const popover = screen.getByRole('dialog', { name: chipLabel });
      for (const message of messages) {
        // The backend's reason text, verbatim.
        expect(within(popover).getByText(message)).toBeInTheDocument();
      }
    },
  );

  it('FRG-UI-037 — a completed-but-unimported download stays visible with an Awaiting import label', async () => {
    // The mid-pipeline state (SAB complete, foragerr import not yet run) is
    // `import_pending`: it must not vanish from the Queue, and it renders a
    // distinct awaiting-import label rather than a bare/empty row (F19).
    const envelope = mockQueueEnvelope([
      mockQueueRecord({
        id: 920,
        state: 'import_pending',
        status: 'ok',
        statusMessages: [],
      }),
    ]);
    const { fetcher } = fakeFetcher(() => envelope);
    renderWithProviders(<QueueScreen />, { fetcher });

    const row = await screen.findByTestId('queue-row-920');
    expect(within(row).getByRole('button', { name: 'Awaiting import' })).toBeInTheDocument();
  });

  it('FRG-UI-006 — remove dialog offers delete-data and blocklist options and confirming issues the DELETE', async () => {
    const { spy, fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/queue?')
        ? mockQueuePage1
        : { id: 900, removed: true, blocklisted: true },
    );
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-900');
    await user.click(screen.getByRole('button', { name: 'Remove Chapter Forty-One' }));

    const dialog = screen.getByRole('dialog', { name: /Remove Saga #41/ });
    const deleteData = within(dialog).getByRole('checkbox', {
      name: /Remove from download client and delete data/,
    });
    const blocklist = within(dialog).getByRole('checkbox', {
      name: /Blocklist release/,
    });

    await user.click(blocklist);
    await user.click(deleteData);
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/queue/900?blocklist=true&deleteData=true',
        expect.objectContaining({ method: 'DELETE' }),
      ),
    );
    // The dialog closes on success.
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: /Remove Saga #41/ })).toBeNull(),
    );
  });

  it('FRG-UI-006 — cancelling the remove dialog issues no request', async () => {
    const { spy, fetcher } = fakeFetcher(() => mockQueuePage1);
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-900');
    await user.click(screen.getByRole('button', { name: 'Remove Chapter Forty-One' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).toBeNull();
    // Only the initial queue GET happened.
    expect(spy).toHaveBeenCalledTimes(1);
  });
});

/** Two failed rows plus one live download — the shape a stalled queue has. */
const mockQueueWithFailures = mockQueueEnvelope([
  mockQueueRecord({
    id: 900,
    issueId: 411,
    issue: { id: 411, issueNumber: '41', title: 'Chapter Forty-One' },
    size: 100,
    sizeleft: 90,
  }),
  mockQueueRecord({
    id: 930,
    state: 'failed',
    status: 'error',
    size: 100,
    sizeleft: 100,
    statusMessages: ['Download failed at the client'],
  }),
  mockQueueRecord({
    id: 931,
    state: 'failed',
    status: 'error',
    size: 100,
    sizeleft: 100,
    statusMessages: ['Download failed at the client'],
  }),
]);

describe('FRG-UI-006: queue table stays inside its frame', () => {
  it('FRG-UI-006 — the table scrolls in its own container and the title column wraps instead of widening the page', () => {
    // jsdom lays nothing out, so containment is asserted on the stylesheet: the
    // scroll box exists, the release-name column may break mid-token, and the
    // table chrome is the shared scaffold rather than a local copy free to drift.
    expect(queueCss).toMatch(/\.tableWrap\s*\{[^}]*overflow-x:\s*auto/);
    expect(queueCss).toMatch(/\.titleCell\s*\{[^}]*overflow-wrap:\s*anywhere/);
    expect(queueCss).toMatch(/\.table\s*\{\s*composes: table from/);
    // `display: flex` on a <td> opts the cell out of column negotiation, which
    // is what pushed the actions past the right edge; the buttons flex inside it.
    expect(queueCss).not.toMatch(/\.actionsCell\s*\{[^}]*display:\s*flex/);
    expect(queueCss).toMatch(/\.actionsGroup\s*\{[^}]*display:\s*flex/);
  });

  it('FRG-UI-006 — the rendered table sits inside the scroll container and the title cell carries the wrapping column style', async () => {
    const { fetcher } = fakeFetcher(() => mockQueuePage1);
    renderWithProviders(<QueueScreen />, { fetcher });

    const wrap = await screen.findByTestId('queue-table-wrap');
    expect(wrap).toHaveClass(styles.tableWrap);
    expect(within(wrap).getByRole('table')).toBeInTheDocument();
    expect(screen.getByText('Chapter Forty-One')).toHaveClass(styles.titleCell);
  });
});

describe('FRG-UI-006: failed rows read by status, not by progress noise', () => {
  it('FRG-UI-006 — a failed row renders no progress bar and no byte counts, and its series/issue still identify it', async () => {
    const { fetcher } = fakeFetcher(() => mockQueueWithFailures);
    renderWithProviders(<QueueScreen />, { fetcher });

    const failedRow = await screen.findByTestId('queue-row-930');
    expect(within(failedRow).queryByRole('progressbar')).toBeNull();
    expect(screen.queryByTestId('queue-progress-930')).toBeNull();
    expect(within(failedRow).queryByText(/left of/)).toBeNull();
    // Status carries the row; the columns still say which comic it is, even
    // though its title is the raw download token.
    expect(within(failedRow).getByRole('button', { name: 'Failed' })).toBeInTheDocument();
    expect(within(failedRow).getByText('Saga')).toBeInTheDocument();
    expect(within(failedRow).getByText('#41')).toBeInTheDocument();
    // The live row keeps its progress.
    expect(screen.getByTestId('queue-progress-900')).toHaveTextContent('10%');
  });

  it('FRG-UI-006 — a failed_pending row drops the same progress noise, and Clear failed still leaves it alone', async () => {
    // Mid-transition through the failure loop: its bytes are as stale as a
    // terminal failure's, but de-tracking it would pull it out from under the
    // loop that is still deciding what it becomes.
    const envelope = mockQueueEnvelope([
      mockQueueRecord({
        id: 940,
        state: 'failed_pending',
        status: 'error',
        size: 100,
        sizeleft: 100,
      }),
    ]);
    const { fetcher } = fakeFetcher(() => envelope);
    renderWithProviders(<QueueScreen />, { fetcher });

    const row = await screen.findByTestId('queue-row-940');
    expect(within(row).queryByRole('progressbar')).toBeNull();
    expect(within(row).queryByText(/left of/)).toBeNull();
    expect(within(row).getByText('Failing')).toBeInTheDocument();
    // Not part of the failure backlog Clear failed sweeps.
    expect(screen.getByRole('button', { name: 'Clear failed' })).toBeDisabled();
  });
});

describe('FRG-UI-006: selection and bulk cleanup', () => {
  it('FRG-UI-006 — select-all then Remove selected issues ONE bulk request carrying the ids and the chosen options', async () => {
    const { spy, fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/queue?')
        ? mockQueuePage1
        : { applied: 2, errors: {} },
    );
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-900');
    await user.click(screen.getByRole('checkbox', { name: 'Select all queue items' }));
    expect(screen.getByTestId('queue-selection-count')).toHaveTextContent('2 selected');

    await user.click(screen.getByRole('button', { name: 'Remove selected' }));
    const dialog = screen.getByRole('dialog', { name: /Remove 2 queue items/ });
    await user.click(within(dialog).getByRole('checkbox', { name: /Blocklist release/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/queue/remove', {
        method: 'POST',
        body: { ids: [900, 901], blocklist: true, deleteData: false },
      }),
    );
    // One request for the whole selection, not one DELETE per row.
    const bulkCalls = spy.mock.calls.filter(([path]) => path === '/api/v1/queue/remove');
    expect(bulkCalls).toHaveLength(1);
  });

  it('FRG-UI-006 — a row the server refuses is reported by name and stays listed and selected', async () => {
    const refusal = 'import in progress for this item; try again once it completes';
    const { fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/queue?')
        ? mockQueuePage1
        : { applied: 1, errors: { 901: refusal } },
    );
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-900');
    await user.click(screen.getByRole('checkbox', { name: 'Select all queue items' }));
    await user.click(screen.getByRole('button', { name: 'Remove selected' }));
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }),
    );

    const notice = await screen.findByRole('alert');
    // Named by its comic, with the backend's reason verbatim.
    expect(within(notice).getByText(`Saga #42: ${refusal}`)).toBeInTheDocument();
    // The row it names is still in the table, and still selected for a retry.
    expect(screen.getByTestId('queue-row-901')).toBeInTheDocument();
    expect(screen.getByTestId('queue-selection-count')).toHaveTextContent('1 selected');
  });

  it('FRG-UI-006 — Clear failed asks the server for the whole failed SCOPE, not the ids on this page', async () => {
    const { spy, fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/queue?')
        ? mockQueueWithFailures
        : { applied: 2, errors: {} },
    );
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-930');
    await user.click(screen.getByRole('button', { name: 'Clear failed' }));

    // The same dialog, with the same explicit options — no hidden blocklist.
    const dialog = screen.getByRole('dialog', { name: /Remove 2 failed queue items/ });
    expect(within(dialog).getByRole('checkbox', { name: /Blocklist release/ })).not.toBeChecked();
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/queue/remove', {
        method: 'POST',
        // No ids: the server selects every failed row, so the downloading row
        // (900) is out of scope without this client having to say so.
        body: { scope: 'failed', blocklist: false, deleteData: false },
      }),
    );
  });

  it('FRG-UI-006 — Clear failed is offered for failures on pages this screen never loaded', async () => {
    // The motivating case: page 1 is all live downloads, and the failure
    // backlog sits on page 3. A page-derived count would grey the button out.
    const envelope = { ...mockQueuePage1, totalRecords: 45, failedRecords: 7 };
    const { spy, fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/queue?') ? envelope : { applied: 7, errors: {} },
    );
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-900');
    const clear = screen.getByRole('button', { name: 'Clear failed' });
    expect(clear).toBeEnabled();

    await user.click(clear);
    const dialog = screen.getByRole('dialog', { name: /Remove 7 failed queue items/ });
    // The confirmation counts the backlog and says the rows it cannot name.
    expect(within(dialog).getByText('…and 7 more on other pages')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Remove' }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/queue/remove', {
        method: 'POST',
        body: { scope: 'failed', blocklist: false, deleteData: false },
      }),
    );
  });

  it('FRG-UI-006 — Clear failed is unavailable while nothing has failed', async () => {
    const { fetcher } = fakeFetcher(() => mockQueuePage1);
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-900');
    expect(screen.getByRole('button', { name: 'Clear failed' })).toBeDisabled();
  });

  it('FRG-UI-006 — a 409 the single-item DELETE throws is shown in the dialog rather than swallowed', async () => {
    // The single-row path is a bare DELETE, so a refusal arrives as a thrown
    // 4xx instead of the bulk endpoint's per-row errors map.
    const { fetcher } = fakeFetcher((path) => {
      if (path.startsWith('/api/v1/queue?')) return mockQueuePage1;
      throw new ApiRequestError(
        409,
        {
          message: 'import in progress for this item; try again once it completes',
          errors: [],
        },
        path,
      );
    });
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-900');
    await user.click(screen.getByRole('button', { name: 'Remove Chapter Forty-One' }));
    const dialog = screen.getByRole('dialog', { name: /Remove Saga #41/ });
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }));

    const alert = await within(dialog).findByRole('alert');
    expect(alert).toHaveTextContent(/import in progress for this item/);
    // The dialog stays open on failure — the row was not removed.
    expect(screen.getByRole('dialog', { name: /Remove Saga #41/ })).toBeInTheDocument();
  });
});

describe('FRG-UI-006: selection and notices are page-scoped', () => {
  /** Page 1 holds a refusable row; page 2 holds a different one. */
  const pagedFetcher = () =>
    fakeFetcher((path) => {
      if (path.includes('page=2')) {
        return {
          ...mockQueueEnvelope([
            mockQueueRecord({
              id: 950,
              issue: { id: 450, issueNumber: '50', title: 'Chapter Fifty' },
            }),
          ]),
          page: 2,
          totalRecords: 45,
        };
      }
      if (path.startsWith('/api/v1/queue?')) {
        return { ...mockQueuePage1, totalRecords: 45 };
      }
      return { applied: 0, errors: { 901: 'import in progress for this item' } };
    });

  it('FRG-UI-006 — turning the page drops the selection, so a bulk remove never carries invisible rows', async () => {
    const { fetcher } = pagedFetcher();
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-900');
    await user.click(screen.getByRole('checkbox', { name: 'Select all queue items' }));
    expect(screen.getByTestId('queue-selection-count')).toHaveTextContent('2 selected');

    await user.click(screen.getByRole('button', { name: 'Next ›' }));
    await screen.findByTestId('queue-row-950');

    // The bulk bar counts only this page's rows, so it must not survive the move.
    expect(screen.queryByTestId('queue-selection-count')).toBeNull();
    expect(screen.getByRole('checkbox', { name: 'Select all queue items' })).not.toBeChecked();
  });

  it('FRG-UI-006 — a refusal notice clears on the next page and on the next remove attempt', async () => {
    const { fetcher } = pagedFetcher();
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-900');
    await user.click(screen.getByRole('checkbox', { name: 'Select all queue items' }));
    await user.click(screen.getByRole('button', { name: 'Remove selected' }));
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }),
    );
    expect(await screen.findByRole('alert')).toBeInTheDocument();

    // Opening the dialog again retires the previous attempt's report.
    await user.click(screen.getByRole('button', { name: 'Remove Chapter Forty-One' }));
    expect(screen.queryByRole('alert')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    // And so does leaving the page it described.
    await user.click(screen.getByRole('checkbox', { name: 'Select all queue items' }));
    await user.click(screen.getByRole('button', { name: 'Remove selected' }));
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }),
    );
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next ›' }));
    await screen.findByTestId('queue-row-950');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('FRG-UI-006 — two rows refused with the identical message are both reported', async () => {
    // Keyed by message, the second row would collide with the first and vanish.
    const reason = 'import in progress for this item';
    const { fetcher } = fakeFetcher((path) =>
      path.startsWith('/api/v1/queue?')
        ? mockQueuePage1
        : { applied: 0, errors: { 900: reason, 901: reason } },
    );
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-900');
    await user.click(screen.getByRole('checkbox', { name: 'Select all queue items' }));
    await user.click(screen.getByRole('button', { name: 'Remove selected' }));
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }),
    );

    const notice = await screen.findByRole('alert');
    expect(within(notice).getAllByRole('listitem')).toHaveLength(2);
    expect(within(notice).getByText(`Saga #41: ${reason}`)).toBeInTheDocument();
    expect(within(notice).getByText(`Saga #42: ${reason}`)).toBeInTheDocument();
  });

  it('FRG-UI-006 — emptying the last page falls back to the page that still has rows', async () => {
    // Clearing the tail of the queue must not strand the screen on a page past
    // the end, showing an empty table over live rows.
    let totalRecords = 21;
    const { fetcher } = fakeFetcher((path) => {
      if (!path.startsWith('/api/v1/queue?')) return { applied: 1, errors: {} };
      const page = path.includes('page=2') ? 2 : 1;
      if (page === 2 && totalRecords <= 20) {
        return { ...mockQueueEnvelope([]), page: 2, totalRecords };
      }
      return {
        ...(page === 2
          ? mockQueueEnvelope([mockQueueRecord({ id: 960 })])
          : mockQueuePage1),
        page,
        totalRecords,
      };
    });
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-900');
    await user.click(screen.getByRole('button', { name: 'Next ›' }));
    await screen.findByTestId('queue-row-960');

    totalRecords = 20;
    await user.click(screen.getByRole('button', { name: 'Refresh' }));

    await waitFor(() =>
      expect(screen.getByTestId('page-controls-label')).toHaveTextContent('Page 1 of 1'),
    );
    expect(await screen.findByTestId('queue-row-900')).toBeInTheDocument();
  });
});

describe('FRG-UI-006: the queue pages', () => {
  it('FRG-UI-006 — page controls render from the envelope and move the screen off page 1', async () => {
    const page2 = {
      ...mockQueueEnvelope([
        mockQueueRecord({
          id: 950,
          issue: { id: 450, issueNumber: '50', title: 'Chapter Fifty' },
        }),
      ]),
      page: 2,
      totalRecords: 45,
    };
    const { spy, fetcher } = fakeFetcher((path) =>
      path.includes('page=2') ? page2 : { ...mockQueuePage1, totalRecords: 45 },
    );
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    await screen.findByTestId('queue-row-900');
    // 45 records at the endpoint's page size of 20.
    expect(screen.getByTestId('page-controls-label')).toHaveTextContent('Page 1 of 3');

    await user.click(screen.getByRole('button', { name: 'Next ›' }));

    await waitFor(() => expect(spy).toHaveBeenCalledWith('/api/v1/queue?page=2'));
    expect(await screen.findByTestId('queue-row-950')).toBeInTheDocument();
    expect(screen.getByTestId('page-controls-label')).toHaveTextContent('Page 2 of 3');
  });
});
