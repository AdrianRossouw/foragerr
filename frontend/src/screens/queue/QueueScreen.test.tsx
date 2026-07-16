import { describe, it, expect } from 'vitest';
import { screen, waitFor, act, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  mockQueueEnvelope,
  mockQueuePage1,
  mockQueueRecord,
} from '../../test/mockData';
import { makeFakeSocketFactory } from '../../test/fakeSocket';
import { WebSocketBridge } from '../../ws/WebSocketBridge';
import { QueueScreen } from './QueueScreen';

/**
 * FRG-UI-006 — Activity: queue screen. Rows render from the /api/v1/queue
 * paging envelope, live-update via the WebSocketBridge queue-progress patch
 * (fakeSocket-driven, no refetch), expose import_pending/import_blocked reason
 * popovers, and remove via a dialog with delete-data + blocklist options.
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
