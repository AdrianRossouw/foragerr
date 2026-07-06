import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { makeCommand, makeScheduledTask } from '../../test/mockData';
import { ApiRequestError } from '../../api/fetcher';
import { TasksScreen } from './TasksScreen';

/**
 * FRG-UI-016 — System: Tasks screen. Renders GET /api/v1/system/task (name,
 * interval, last/next run, command); force-run POSTs
 * /api/v1/system/task/{name} and tracks the returned command to terminal,
 * with last/next-run reflecting the finished run afterwards. The
 * `backup-database` row's action is "Back up now" — the same endpoint.
 */

describe('FRG-UI-016: system tasks screen', () => {
  it('FRG-UI-016 — Task list shows schedule state and the command each runs', async () => {
    const tasks = [
      makeScheduledTask({
        name: 'backup-database',
        command_name: 'backup-database',
        label: 'Database Backup',
        interval_seconds: 86_400,
        last_run: '2026-07-05T03:00:00Z',
        next_run: '2026-07-06T03:00:00Z',
      }),
      makeScheduledTask({
        name: 'refresh-metadata',
        command_name: 'refresh-metadata',
        label: 'Refresh Metadata',
        interval_seconds: 3_600,
      }),
    ];
    const { spy, fetcher } = fakeFetcher(() => tasks);
    renderWithProviders(<TasksScreen />, { fetcher });

    const row = await screen.findByTestId('task-row-backup-database');
    expect(spy).toHaveBeenCalledWith('/api/v1/system/task');
    expect(within(row).getByText('Database Backup')).toBeInTheDocument();
    expect(within(row).getByText('Every 1d')).toBeInTheDocument();

    expect(
      screen.getByTestId('task-row-refresh-metadata'),
    ).toHaveTextContent('Refresh Metadata');
  });

  it('FRG-UI-016 — force-running a task POSTs to /api/v1/system/task/{name} and tracks its command to terminal, updating last/next run afterwards', async () => {
    let tasks = [
      makeScheduledTask({
        name: 'refresh-metadata',
        label: 'Refresh Metadata',
        last_run: '2026-07-05T03:00:00Z',
        next_run: '2026-07-06T03:00:00Z',
      }),
    ];
    let taskListCalls = 0;
    const { spy, fetcher } = fakeFetcher((path, init) => {
      if (path === '/api/v1/system/task') {
        taskListCalls += 1;
        return tasks;
      }
      if (init?.method === 'POST' && path === '/api/v1/system/task/refresh-metadata') {
        return makeCommand({ id: 501, name: 'refresh-metadata', status: 'queued' });
      }
      if (path === '/api/v1/command/501') {
        // The finished run: a subsequent GET /system/task reflects the new
        // last/next run — this is what the invalidation-on-terminal proves.
        tasks = [
          { ...tasks[0], last_run: '2026-07-06T15:00:00Z', next_run: '2026-07-07T15:00:00Z' },
        ];
        return makeCommand({
          id: 501,
          name: 'refresh-metadata',
          status: 'completed',
          finished_at: '2026-07-06T15:00:01Z',
        });
      }
      throw new Error(`unexpected request: ${path}`);
    });
    const user = userEvent.setup();
    renderWithProviders(<TasksScreen />, { fetcher });

    const row = await screen.findByTestId('task-row-refresh-metadata');
    await user.click(within(row).getByRole('button', { name: 'Run Now' }));

    expect(spy).toHaveBeenCalledWith('/api/v1/system/task/refresh-metadata', {
      method: 'POST',
    });
    await waitFor(() =>
      expect(screen.getByTestId('task-status-refresh-metadata')).toHaveTextContent(
        'completed',
      ),
    );
    // The list re-fetches both immediately on force-run (timer reset) and
    // again once the command reaches terminal, so the row's last/next run
    // reflect the finished run.
    await waitFor(() => expect(taskListCalls).toBe(3));
    await waitFor(() =>
      expect(within(screen.getByTestId('task-row-refresh-metadata')).getByText('Jul 6, 2026')).toBeInTheDocument(),
    );
  });

  it('FRG-UI-016 — "Back up now" force-runs the backup-database task via the same endpoint', async () => {
    const tasks = [
      makeScheduledTask({ name: 'backup-database', label: 'Database Backup' }),
    ];
    const { spy, fetcher } = fakeFetcher((path, init) => {
      if (path === '/api/v1/system/task') return tasks;
      if (init?.method === 'POST' && path === '/api/v1/system/task/backup-database') {
        return makeCommand({ id: 601, name: 'backup-database', status: 'queued' });
      }
      if (path === '/api/v1/command/601') {
        return makeCommand({ id: 601, name: 'backup-database', status: 'started' });
      }
      throw new Error(`unexpected request: ${path}`);
    });
    const user = userEvent.setup();
    renderWithProviders(<TasksScreen />, { fetcher });

    const row = await screen.findByTestId('task-row-backup-database');
    await user.click(within(row).getByRole('button', { name: 'Back up now' }));

    expect(spy).toHaveBeenCalledWith('/api/v1/system/task/backup-database', {
      method: 'POST',
    });
    await waitFor(() =>
      expect(screen.getByTestId('task-status-backup-database')).toHaveTextContent(
        'started',
      ),
    );
  });

  it('FRG-UI-016 — a force-run failure surfaces inline and clears on the next successful run', async () => {
    const tasks = [
      makeScheduledTask({ name: 'refresh-metadata', label: 'Refresh Metadata' }),
    ];
    let shouldFail = true;
    const { fetcher } = fakeFetcher((path, init) => {
      if (path === '/api/v1/system/task') return tasks;
      if (init?.method === 'POST' && path === '/api/v1/system/task/refresh-metadata') {
        if (shouldFail) {
          shouldFail = false;
          throw new ApiRequestError(
            500,
            { message: 'Internal Server Error', errors: [] },
            path,
          );
        }
        return makeCommand({ id: 701, name: 'refresh-metadata', status: 'completed' });
      }
      if (path === '/api/v1/command/701') {
        return makeCommand({ id: 701, name: 'refresh-metadata', status: 'completed' });
      }
      throw new Error(`unexpected request: ${path}`);
    });
    const user = userEvent.setup();
    renderWithProviders(<TasksScreen />, { fetcher });

    const row = await screen.findByTestId('task-row-refresh-metadata');
    const button = within(row).getByRole('button', { name: 'Run Now' });
    await user.click(button);

    await waitFor(() =>
      expect(screen.getByTestId('task-error-refresh-metadata')).toHaveTextContent(
        'Internal Server Error',
      ),
    );
    // The button re-enables immediately — a failed force-run started nothing
    // to watch, so it must not stay disabled.
    expect(button).not.toBeDisabled();

    await user.click(button);

    await waitFor(() =>
      expect(
        screen.queryByTestId('task-error-refresh-metadata'),
      ).not.toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByTestId('task-status-refresh-metadata')).toHaveTextContent(
        'completed',
      ),
    );
  });

  it('FRG-UI-016 — a persistent command-status poll failure surfaces an error state instead of a stuck "queued" chip', async () => {
    const tasks = [
      makeScheduledTask({ name: 'refresh-metadata', label: 'Refresh Metadata' }),
    ];
    const { fetcher } = fakeFetcher((path, init) => {
      if (path === '/api/v1/system/task') return tasks;
      if (init?.method === 'POST' && path === '/api/v1/system/task/refresh-metadata') {
        return makeCommand({ id: 801, name: 'refresh-metadata', status: 'queued' });
      }
      if (path === '/api/v1/command/801') {
        // The command was accepted (POST succeeded); it is the WATCH poll
        // itself that keeps failing — the chip must not stay stuck "queued".
        throw new ApiRequestError(500, null, path);
      }
      throw new Error(`unexpected request: ${path}`);
    });
    const user = userEvent.setup();
    renderWithProviders(<TasksScreen />, { fetcher });

    const row = await screen.findByTestId('task-row-refresh-metadata');
    const button = within(row).getByRole('button', { name: 'Run Now' });
    await user.click(button);

    await waitFor(() =>
      expect(screen.getByTestId('task-status-refresh-metadata')).toHaveTextContent(
        'error',
      ),
    );
    expect(button).not.toBeDisabled();
  });
});
