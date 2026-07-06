import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { createQueryClient } from '../../queryClient';
import {
  makeCommand,
  makeManualEntry,
  makeSeriesResource,
  mockIssues,
  mockManualCandidates,
  mockQueueEnvelope,
  mockQueueRecord,
  pageOf,
} from '../../test/mockData';
import type { FetcherInit } from '../../api/fetcher';
import { ManualImportOverlay } from './ManualImportOverlay';
import { QueueScreen } from './QueueScreen';

/**
 * FRG-UI-014 — Manual import overlay: candidate files render in the endpoint's
 * order with their would-be decisions; blocked rows expose verbatim rejection
 * reasons; series/issue/format controls are pre-filled from the API's suggested
 * mapping (issue picker scoped to the chosen series, verified embedded ComicInfo
 * badged); the footer posts the corrected mappings as one manual-import command
 * and reflects its outcome. Reachable from an ImportBlocked queue row and from a
 * toolbar path picker.
 */

const SERIES_INDEX = [makeSeriesResource({ id: 7, title: 'Invincible' })];

/**
 * Backing resolver for the auxiliary reads the overlay makes (series index,
 * per-series issues) plus a customizable manual-import list + command status.
 */
function makeResolver(opts: {
  list: (call: number, init?: FetcherInit) => unknown;
  command?: () => unknown;
}) {
  let listCalls = 0;
  return (path: string, init?: FetcherInit): unknown => {
    if (path.startsWith('/api/v1/manual-import')) {
      if (init?.method === 'POST') {
        return makeCommand({ id: 77, name: 'manual-import', status: 'started' });
      }
      listCalls += 1;
      return opts.list(listCalls, init);
    }
    if (path.startsWith('/api/v1/command/')) {
      return (opts.command ?? (() => makeCommand({ id: 77, name: 'manual-import', status: 'completed' })))();
    }
    if (path.startsWith('/api/v1/series?')) return pageOf(SERIES_INDEX);
    if (path.startsWith('/api/v1/issues?')) return pageOf(mockIssues);
    throw new Error(`unexpected request: ${path}`);
  };
}

describe('FRG-UI-014: manual import overlay', () => {
  it('FRG-UI-014 — reachable from an ImportBlocked queue row: opens for that download and imports once a valid override is applied', async () => {
    const blocked = mockQueueEnvelope([
      mockQueueRecord({
        id: 920,
        state: 'import_blocked',
        status: 'warning',
        statusMessages: ['No files eligible for import'],
        issue: { id: 411, issueNumber: '41', title: 'Blocked Book' },
      }),
    ]);
    const { spy, fetcher } = fakeFetcher((path, init) => {
      if (path.startsWith('/api/v1/queue?')) return blocked;
      return makeResolver({
        list: () => [
          makeManualEntry({
            path: '/dl/SABnzbd_nzo_920/mystery.cbr',
            approved: false,
            rejections: ['No series match for parsed title'],
            format: 'cbr',
          }),
        ],
      })(path, init);
    });
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    // The ImportBlocked row exposes a Manual import action alongside remove.
    await screen.findByTestId('queue-row-920');
    await user.click(screen.getByRole('button', { name: 'Manual import Blocked Book' }));

    // The overlay lists that download's candidates (GET keyed by downloadId).
    await screen.findByTestId('manual-row-mystery.cbr');
    expect(spy).toHaveBeenCalledWith(
      '/api/v1/manual-import?downloadId=SABnzbd_nzo_920',
    );

    // A blocked row is not importable until an override supplies series + issue.
    const checkbox = screen.getByRole('checkbox', { name: 'Select mystery.cbr' });
    expect(checkbox).toBeDisabled();

    await user.selectOptions(
      screen.getByLabelText('Series for mystery.cbr'),
      '7',
    );
    await waitFor(() =>
      within(screen.getByLabelText('Issue for mystery.cbr') as HTMLElement)
        .getByRole('option', { name: '1 — Family Matters' }),
    );
    await user.selectOptions(screen.getByLabelText('Issue for mystery.cbr'), '71');

    // Now selectable; select it and import.
    expect(checkbox).toBeEnabled();
    await user.click(checkbox);
    await user.click(screen.getByRole('button', { name: 'Import 1 selected' }));

    // Opened from a blocked download → the POST carries that downloadId so the
    // backend re-evaluates with download scope (AlreadyImportedSpec etc.).
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/manual-import',
        expect.objectContaining({
          method: 'POST',
          body: {
            downloadId: 'SABnzbd_nzo_920',
            files: [
              {
                path: '/dl/SABnzbd_nzo_920/mystery.cbr',
                seriesId: 7,
                issueId: 71,
                format: 'cbr',
              },
            ],
          },
        }),
      ),
    );
  });

  it('FRG-UI-014 — a path-picker overlay POSTs without a downloadId (no download scope)', async () => {
    const { spy, fetcher } = fakeFetcher(
      makeResolver({
        list: () => [
          makeManualEntry({
            path: '/comics/_unsorted/Invincible 001.cbz',
            approved: true,
            suggestedSeriesId: 7,
            suggestedIssueId: 71,
            format: 'cbz',
          }),
        ],
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <ManualImportOverlay
        source={{ kind: 'path', path: '/comics/_unsorted' }}
        onClose={() => {}}
      />,
      { fetcher },
    );

    // The approved row is preselected — import straight away.
    await screen.findByTestId('manual-row-Invincible 001.cbz');
    await user.click(await screen.findByRole('button', { name: 'Import 1 selected' }));

    // Opened via the path picker → the POST body is JUST { files }, no downloadId.
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/manual-import',
        expect.objectContaining({
          method: 'POST',
          body: {
            files: [
              {
                path: '/comics/_unsorted/Invincible 001.cbz',
                seriesId: 7,
                issueId: 71,
                format: 'cbz',
              },
            ],
          },
        }),
      ),
    );
  });

  it('FRG-UI-014 — reachable from the path picker: lists that folder’s candidates with per-file controls', async () => {
    const inner = makeResolver({ list: () => mockManualCandidates });
    const { spy, fetcher } = fakeFetcher((path, init) =>
      path.startsWith('/api/v1/queue?')
        ? mockQueueEnvelope([]) // empty queue; the picker is a toolbar affordance
        : inner(path, init),
    );
    const user = userEvent.setup();
    renderWithProviders(<QueueScreen />, { fetcher });

    // The path picker is a toolbar affordance independent of the queue rows.
    await user.type(
      screen.getByLabelText('Manual import folder path'),
      '/comics/_unsorted',
    );
    await user.click(screen.getByRole('button', { name: 'Manual import' }));

    await screen.findByTestId('manual-row-Invincible 001.cbz');
    expect(spy).toHaveBeenCalledWith(
      `/api/v1/manual-import?path=${encodeURIComponent('/comics/_unsorted')}`,
    );
    // Both candidates render, in response order, each with override controls.
    expect(screen.getByLabelText('Series for Invincible 001.cbz')).toBeInTheDocument();
    expect(screen.getByLabelText('Format for mystery 002.cbr')).toBeInTheDocument();
  });

  it('FRG-UI-014 — per-file override controls are pre-filled; the issue picker is scoped to the chosen series; a verified embedded suggestion is badged', async () => {
    const { fetcher } = fakeFetcher(
      makeResolver({ list: () => mockManualCandidates }),
    );
    renderWithProviders(
      <ManualImportOverlay
        source={{ kind: 'path', path: '/comics/_unsorted' }}
        onClose={() => {}}
      />,
      { fetcher },
    );

    await screen.findByTestId('manual-row-Invincible 001.cbz');

    // Series + format pre-filled from the API's suggested values.
    const seriesSel = screen.getByLabelText('Series for Invincible 001.cbz') as HTMLSelectElement;
    expect(seriesSel.value).toBe('7');
    const formatSel = screen.getByLabelText('Format for Invincible 001.cbz') as HTMLSelectElement;
    expect(formatSel.value).toBe('cbz');

    // Issue picker scoped to series 7 and pre-filled to the suggested issue.
    const issueSel = screen.getByLabelText('Issue for Invincible 001.cbz') as HTMLSelectElement;
    await waitFor(() => expect(issueSel.value).toBe('71'));
    // Its options are series-7 issues (the string-number "1.5" from that series).
    expect(within(issueSel).getByRole('option', { name: /1\.5/ })).toBeInTheDocument();

    // The verified embedded ComicInfo suggestion is badged; the unverified row is not.
    expect(screen.getByTestId('manual-embedded-Invincible 001.cbz')).toHaveTextContent(
      'from ComicInfo',
    );
    expect(screen.queryByTestId('manual-embedded-mystery 002.cbr')).toBeNull();
  });

  it('FRG-UI-014 — a blocked row renders its rejection reasons verbatim, in order, via the decision popover', async () => {
    const { fetcher } = fakeFetcher(
      makeResolver({ list: () => mockManualCandidates }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <ManualImportOverlay
        source={{ kind: 'path', path: '/comics/_unsorted' }}
        onClose={() => {}}
      />,
      { fetcher },
    );

    const row = await screen.findByTestId('manual-row-mystery 002.cbr');
    // Reasons are hidden until the decision chip is activated.
    expect(screen.queryByText('No series match for parsed title')).not.toBeInTheDocument();

    await user.click(
      within(row).getByRole('button', { name: 'mystery 002.cbr — show reasons' }),
    );
    const popover = screen.getByRole('dialog', { name: 'mystery 002.cbr — show reasons' });
    const items = within(popover).getAllByRole('listitem');
    // Verbatim wording, in the pipeline's order — never paraphrased or re-sorted.
    expect(items.map((li) => li.textContent)).toEqual([
      'No series match for parsed title',
      'Unmapped issue number',
    ]);
  });

  it('FRG-UI-014 — importing posts the corrected mappings; on completion the imported file leaves, still-blocked files re-render with updated reasons, and the queue refreshes', async () => {
    const client = createQueryClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const { spy, fetcher } = fakeFetcher(
      makeResolver({
        list: (call) =>
          call === 1
            ? mockManualCandidates
            : [
                // The approved file imported and left; the blocked file remains
                // with a NEW verbatim reason from the re-evaluation.
                makeManualEntry({
                  path: '/comics/_unsorted/mystery 002.cbr',
                  approved: false,
                  rejections: ['Still no series match after import'],
                  format: 'cbr',
                }),
              ],
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <ManualImportOverlay
        source={{ kind: 'download', downloadId: 'nzo_5' }}
        onClose={() => {}}
      />,
      { fetcher, client },
    );

    // The approved row is preselected — the footer counts it.
    await screen.findByTestId('manual-row-Invincible 001.cbz');
    const confirm = await screen.findByRole('button', { name: 'Import 1 selected' });
    await user.click(confirm);

    // Posts the corrected mapping (suggested series/issue/format carried
    // through) plus the download scope, since this overlay was opened for one.
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/manual-import',
        expect.objectContaining({
          method: 'POST',
          body: {
            downloadId: 'nzo_5',
            files: [
              {
                path: '/comics/Invincible (2003)/Invincible 001.cbz',
                seriesId: 7,
                issueId: 71,
                format: 'cbz',
              },
            ],
          },
        }),
      ),
    );

    // On completion: imported file leaves; the still-blocked file re-renders
    // with its updated reason.
    await waitFor(() =>
      expect(screen.queryByTestId('manual-row-Invincible 001.cbz')).toBeNull(),
    );
    const remaining = screen.getByTestId('manual-row-mystery 002.cbr');
    await user.click(
      within(remaining).getByRole('button', { name: 'mystery 002.cbr — show reasons' }),
    );
    expect(
      screen.getByText('Still no series match after import'),
    ).toBeInTheDocument();

    // The queue view is invalidated so it reflects the now-imported download.
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['queue'] });
  });
});
