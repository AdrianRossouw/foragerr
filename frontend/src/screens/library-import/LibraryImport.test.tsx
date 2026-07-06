import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  makeCommand,
  makeLibraryImportGroup,
  mockFormatProfiles,
  mockLookupCandidates,
  mockRootFolders,
  pageOf,
} from '../../test/mockData';
import { ApiRequestError, type FetcherInit } from '../../api/fetcher';
import { LibraryImport } from './LibraryImport';
import { toLibraryImportGroup } from './libraryImportHooks';

/**
 * FRG-UI-015 — Library import screen: pick a configured root folder, scan it
 * as a watched command (running state visible), review the staged groups
 * (folder, file count, parse confidence, proposed ComicVine match or an
 * explicit no-match state), correct matches through the inline ComicVine
 * lookup, then bulk-add the selected groups with batch add options and see
 * per-group imported/blocked outcomes (blocked reasons verbatim). Negative
 * states — no roots configured, scan found nothing — are explicit, never a
 * blank results area. Fake fetcher only.
 */

/** A staged group with a proposed match, Sonarr-import style. */
const proposedGroup = makeLibraryImportGroup({
  id: 2,
  folder: '/comics/Saga (2012)',
  matchingKey: 'saga',
  files: ['/comics/Saga (2012)/Saga 001.cbz', '/comics/Saga (2012)/Saga 002.cbz'],
  confidence: 0.9,
});

/** A staged group the scan could not match — requires an explicit choice. */
const noMatchGroup = makeLibraryImportGroup({
  id: 3,
  folder: '/comics/Unknown Mini',
  matchingKey: 'unknown mini',
  files: ['/comics/Unknown Mini/Unknown Mini 001.cbz'],
  confidence: 0.3,
  state: 'no_match',
  proposedCvVolumeId: null,
  name: null,
  startYear: null,
  publisher: null,
});

/**
 * Backing resolver for the screen's reads/commands. `groups` receives the
 * 1-based GET /library-import call number, so tests can vary the staged list
 * across the post-command/PATCH refetches.
 */
function makeResolver(opts: {
  groups: (call: number) => unknown[];
  command?: (id: number, call: number) => unknown;
  lookup?: (path: string) => unknown;
}) {
  let groupCalls = 0;
  const commandCalls = new Map<number, number>();
  return (path: string, init?: FetcherInit): unknown => {
    const method = init?.method ?? 'GET';
    if (method === 'GET' && path === '/api/v1/rootfolder') return mockRootFolders;
    if (method === 'GET' && path === '/api/v1/formatprofile') {
      return mockFormatProfiles;
    }
    if (method === 'GET' && path.startsWith('/api/v1/library-import?')) {
      groupCalls += 1;
      return pageOf(opts.groups(groupCalls));
    }
    if (method === 'POST' && path === '/api/v1/library-import/scan') {
      return makeCommand({ id: 81, name: 'library-import-scan', status: 'queued' });
    }
    if (method === 'POST' && path === '/api/v1/library-import/execute') {
      return makeCommand({ id: 82, name: 'library-import', status: 'queued' });
    }
    if (method === 'PATCH' && path.startsWith('/api/v1/library-import/groups/')) {
      return {};
    }
    if (method === 'GET' && path.startsWith('/api/v1/command/')) {
      const id = Number(path.split('/').pop());
      const call = (commandCalls.get(id) ?? 0) + 1;
      commandCalls.set(id, call);
      return opts.command
        ? opts.command(id, call)
        : makeCommand({ id, name: 'library-import-scan', status: 'completed' });
    }
    if (method === 'GET' && path.startsWith('/api/v1/series/lookup?term=')) {
      return (
        opts.lookup ??
        (() => ({ records: mockLookupCandidates, complete: true, truncated: false }))
      )(path);
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  };
}

describe('FRG-UI-015: library import — unconfigured and empty states', () => {
  it('FRG-UI-015 — with no root folders configured the screen says so and points at Settings', async () => {
    const { fetcher } = fakeFetcher((path) => {
      if (path === '/api/v1/rootfolder') return [];
      throw new Error(`unexpected request: ${path}`);
    });
    renderWithProviders(<LibraryImport />, { fetcher });

    const note = await screen.findByTestId('li-unconfigured');
    expect(note).toHaveTextContent(/No root folders are configured/);
    // Points at Settings explicitly...
    expect(
      screen.getByRole('link', { name: 'Media Management settings' }),
    ).toHaveAttribute('href', '/settings/media-management');
    // ...and there is no scan control and no misleading empty-results area.
    expect(screen.queryByTestId('li-scan')).not.toBeInTheDocument();
    expect(screen.queryByTestId('li-empty-unscanned')).not.toBeInTheDocument();
    expect(screen.queryByTestId('li-empty-mapped')).not.toBeInTheDocument();
  });

  it('FRG-UI-015 — a scan that finds nothing renders the explicit fully-mapped empty state, distinct from the pre-scan state', async () => {
    const { fetcher } = fakeFetcher(makeResolver({ groups: () => [] }));
    const user = userEvent.setup();
    renderWithProviders(<LibraryImport />, { fetcher });

    // Before any scan the empty staging is "run a scan", never "fully mapped".
    await screen.findByTestId('li-empty-unscanned');
    expect(screen.queryByTestId('li-empty-mapped')).not.toBeInTheDocument();

    await user.click(await screen.findByTestId('li-scan'));

    // The scan command completed and staged nothing: say so explicitly.
    const mapped = await screen.findByTestId('li-empty-mapped');
    expect(mapped).toHaveTextContent(
      'The scan found nothing to import — everything under /comics is already mapped to a series in the library.',
    );
    expect(screen.queryByTestId('li-empty-unscanned')).not.toBeInTheDocument();
  });
});

describe('FRG-UI-015: scan and review proposed matches', () => {
  it('FRG-UI-015 — scanning shows a running command state, then staged groups render with proposal, confidence and an explicit no-match state', async () => {
    let resolveScanStatus!: (value: unknown) => void;
    const pendingScan = new Promise((resolve) => {
      resolveScanStatus = resolve;
    });
    const { spy, fetcher } = fakeFetcher(
      makeResolver({
        // Call 1 = initial mount (nothing staged); call 2 = post-scan refetch.
        groups: (call) => (call === 1 ? [] : [proposedGroup, noMatchGroup]),
        command: (id) =>
          id === 81 ? pendingScan : makeCommand({ id, status: 'completed' }),
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LibraryImport />, { fetcher });

    // Root picker defaults to the first configured root; start the scan.
    await screen.findByTestId('li-empty-unscanned');
    await user.click(screen.getByTestId('li-scan'));

    // The scan is a command POST keyed by the chosen root...
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/library-import/scan', {
        method: 'POST',
        body: { rootFolderId: 1 },
      }),
    );
    // ...with a visible running state while it is live, and no groups yet.
    expect(screen.getByTestId('li-scan-status')).toHaveTextContent('Scan: queued');
    expect(screen.getByTestId('li-scan')).toBeDisabled();
    expect(screen.queryByTestId('li-group-2')).not.toBeInTheDocument();

    // The command completes -> the staged groups refetch and render.
    resolveScanStatus(
      makeCommand({ id: 81, name: 'library-import-scan', status: 'completed' }),
    );
    const matched = await screen.findByTestId('li-group-2');

    // Matched group: folder name, file count, parse confidence, proposal
    // (poster/name/year/publisher) — staged for review, nothing imported.
    expect(within(matched).getByText('Saga (2012)')).toBeInTheDocument();
    expect(within(matched).getByText('2 files')).toBeInTheDocument();
    expect(within(matched).getByText('Confidence 90%')).toBeInTheDocument();
    expect(within(matched).getByText('Saga')).toBeInTheDocument();
    expect(within(matched).getByText('(2012)')).toBeInTheDocument();
    expect(within(matched).getByText('Image')).toBeInTheDocument();
    expect(within(matched).getByText('Proposed')).toBeInTheDocument();

    // Unmatched group: an EXPLICIT no-match state, never a silent blank.
    const unmatched = screen.getByTestId('li-group-3');
    expect(within(unmatched).getByText('1 file')).toBeInTheDocument();
    expect(within(unmatched).getByText('Confidence 30%')).toBeInTheDocument();
    expect(within(unmatched).getByTestId('li-no-match-3')).toHaveTextContent(
      /No plausible ComicVine match/,
    );

    // The scan staged everything for review — nothing has imported.
    expect(screen.queryByText('Imported')).not.toBeInTheDocument();
    // The groups list came from the root-keyed staging endpoint.
    expect(spy).toHaveBeenCalledWith(
      '/api/v1/library-import?rootFolderId=1&page=1&pageSize=200',
    );
  });

  it('FRG-UI-015 — group fields arriving snake_case normalize onto the same rendering', async () => {
    // The backend serializer may follow the snake_case series resources; the
    // normalizer must accept either spelling (types stay tolerant).
    const rawSnake = {
      id: 9,
      matching_key: 'saga',
      folder: '/comics/Saga (2012)',
      files: ['/comics/Saga (2012)/Saga 001.cbz'],
      confidence: 0.42,
      proposed_cv_volume_id: 40501234,
      confirmed_cv_volume_id: null,
      state: 'proposed',
      name: 'Saga',
      start_year: 2012,
      publisher: 'Image',
      image_url: null,
      blocked_reasons: [],
    };
    expect(toLibraryImportGroup(rawSnake).matchingKey).toBe('saga');

    const { fetcher } = fakeFetcher(makeResolver({ groups: () => [rawSnake] }));
    renderWithProviders(<LibraryImport />, { fetcher });

    const card = await screen.findByTestId('li-group-9');
    expect(within(card).getByText('Confidence 42%')).toBeInTheDocument();
    expect(within(card).getByText('Saga')).toBeInTheDocument();
    expect(within(card).getByText('(2012)')).toBeInTheDocument();
    expect(within(card).getByText('Image')).toBeInTheDocument();
    // A proposed group with a volume attached is selectable.
    expect(
      screen.getByRole('checkbox', { name: 'Select Saga (2012)' }),
    ).toBeEnabled();
  });
});

describe('FRG-UI-015: correcting a match before import', () => {
  it('FRG-UI-015 — a no-match group is not selectable until an explicit ComicVine choice confirms it', async () => {
    const { spy, fetcher } = fakeFetcher(
      makeResolver({
        // After the override PATCH the group comes back user-confirmed.
        groups: (call) =>
          call === 1
            ? [noMatchGroup]
            : [
                makeLibraryImportGroup({
                  ...noMatchGroup,
                  state: 'confirmed',
                  confirmedCvVolumeId: 40501234,
                  name: 'Saga',
                  startYear: 2012,
                  publisher: 'Image',
                }),
              ],
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LibraryImport />, { fetcher });

    // No plausible match: the group cannot be selected for import...
    await screen.findByTestId('li-group-3');
    expect(
      screen.getByRole('checkbox', { name: 'Select Unknown Mini' }),
    ).toBeDisabled();
    // ...so no batch panel either.
    expect(screen.queryByTestId('li-batch-panel')).not.toBeInTheDocument();

    // Search ComicVine inline and pick a volume.
    await user.click(screen.getByRole('button', { name: 'Search ComicVine' }));
    await user.type(
      screen.getByRole('searchbox', { name: 'Search ComicVine for Unknown Mini' }),
      'saga',
    );
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await user.click(await screen.findByTestId('li-candidate-40501234'));

    // The choice PATCHes the override (CV-validated server-side)...
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/library-import/groups/3', {
        method: 'PATCH',
        body: { cvVolumeId: 40501234 },
      }),
    );

    // ...and the refetched group is user-confirmed and now selectable.
    await waitFor(() =>
      expect(within(screen.getByTestId('li-group-3')).getByText('Confirmed')).toBeInTheDocument(),
    );
    expect(
      screen.getByRole('checkbox', { name: 'Select Unknown Mini' }),
    ).toBeEnabled();
    expect(screen.getByTestId('li-batch-panel')).toBeInTheDocument();
  });

  it('FRG-UI-015 — rejecting a proposed match and searching inline updates the group to the chosen volume, marked user-confirmed', async () => {
    const { spy, fetcher } = fakeFetcher(
      makeResolver({
        groups: (call) =>
          call === 1
            ? [proposedGroup]
            : [
                makeLibraryImportGroup({
                  ...proposedGroup,
                  state: 'confirmed',
                  confirmedCvVolumeId: 40509999,
                  name: 'Saga of the Swamp Thing',
                  startYear: 1982,
                  publisher: 'DC Comics',
                }),
              ],
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LibraryImport />, { fetcher });

    await screen.findByTestId('li-group-2');
    await user.click(screen.getByRole('button', { name: 'Change match' }));
    await user.type(
      screen.getByRole('searchbox', { name: 'Search ComicVine for Saga (2012)' }),
      'swamp thing',
    );
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await user.click(await screen.findByTestId('li-candidate-40509999'));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/library-import/groups/2', {
        method: 'PATCH',
        body: { cvVolumeId: 40509999 },
      }),
    );

    const card = await screen.findByTestId('li-group-2');
    await waitFor(() =>
      expect(within(card).getByText('Saga of the Swamp Thing')).toBeInTheDocument(),
    );
    expect(within(card).getByText('Confirmed')).toBeInTheDocument();
    expect(within(card).getByText('DC Comics')).toBeInTheDocument();
  });

  it('FRG-UI-015 — confirm and skip actions PATCH the group state', async () => {
    const { spy, fetcher } = fakeFetcher(
      makeResolver({ groups: () => [proposedGroup, noMatchGroup] }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LibraryImport />, { fetcher });

    await screen.findByTestId('li-group-2');
    await user.click(screen.getByRole('button', { name: 'Confirm match' }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/library-import/groups/2', {
        method: 'PATCH',
        body: { action: 'confirm' },
      }),
    );

    const unmatched = screen.getByTestId('li-group-3');
    await user.click(within(unmatched).getByRole('button', { name: 'Skip' }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/library-import/groups/3', {
        method: 'PATCH',
        body: { action: 'skip' },
      }),
    );
  });

  it('FRG-UI-015 — a ComicVine credential failure in the inline lookup renders Settings guidance, not an empty result', async () => {
    const { fetcher } = fakeFetcher(
      makeResolver({
        groups: () => [noMatchGroup],
        lookup: () => {
          throw new ApiRequestError(
            503,
            {
              message: 'comicvine lookup failed: ComicVine rejected the API key',
              errors: [
                {
                  field: 'comicvine_api_key',
                  message: 'ComicVine rejected the API key (missing or invalid)',
                },
              ],
            },
            '/api/v1/series/lookup?term=saga',
          );
        },
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LibraryImport />, { fetcher });

    await screen.findByTestId('li-group-3');
    await user.click(screen.getByRole('button', { name: 'Search ComicVine' }));
    await user.type(
      screen.getByRole('searchbox', { name: 'Search ComicVine for Unknown Mini' }),
      'saga',
    );
    await user.click(screen.getByRole('button', { name: 'Search' }));

    // Structural credential classification, same presentation as the add flow.
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(
      'ComicVine API key missing or invalid — check Settings.',
    );
    expect(screen.queryByText(/No volumes found/)).not.toBeInTheDocument();
  });
});

describe('FRG-UI-015: bulk add with batch options and per-group outcomes', () => {
  it('FRG-UI-015 — importing selected groups posts batch add options (root = the scanned one) and renders imported/blocked outcomes with verbatim reasons', async () => {
    const confirmedGroup = makeLibraryImportGroup({
      id: 4,
      folder: '/comics/Bone',
      matchingKey: 'bone',
      files: ['/comics/Bone/Bone 001.cbz'],
      state: 'confirmed',
      proposedCvVolumeId: null,
      confirmedCvVolumeId: 40509999,
      name: 'Bone',
      startYear: 1991,
      publisher: 'Cartoon Books',
    });
    const { spy, fetcher } = fakeFetcher(
      makeResolver({
        groups: (call) =>
          call === 1
            ? [proposedGroup, confirmedGroup]
            : [
                // Post-execute staging: one imported, one blocked with
                // verbatim reasons from the shared pipeline.
                makeLibraryImportGroup({ ...proposedGroup, state: 'imported' }),
                makeLibraryImportGroup({
                  ...confirmedGroup,
                  rejections: [
                    'Destination file already exists',
                    'Format not allowed by profile',
                  ],
                }),
              ],
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<LibraryImport />, { fetcher });

    // Both importable groups preselect; the batch panel counts them and pins
    // the root folder to the scanned one (no root picker in the batch).
    await screen.findByTestId('li-group-2');
    const panel = await screen.findByTestId('li-batch-panel');
    expect(screen.getByTestId('li-batch-root')).toHaveTextContent('/comics');
    expect(
      within(panel).queryByRole('combobox', { name: 'Root folder' }),
    ).not.toBeInTheDocument();

    // Batch options: format profile, monitor strategy, search-on-add.
    const profile = within(panel).getByRole('combobox', { name: 'Format profile' });
    await waitFor(() =>
      expect(within(profile).getAllByRole('option')).toHaveLength(2),
    );
    await user.selectOptions(profile, '2');
    await user.selectOptions(
      within(panel).getByRole('combobox', { name: 'Monitor strategy' }),
      'existing',
    );
    await user.click(
      within(panel).getByRole('checkbox', { name: 'Start search for missing issues' }),
    );
    await user.click(
      within(panel).getByRole('button', { name: 'Import 2 selected' }),
    );

    // One execute command for the whole batch.
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/library-import/execute', {
        method: 'POST',
        body: {
          groupIds: [2, 4],
          addOptions: {
            formatProfileId: 2,
            monitorStrategy: 'existing',
            searchOnAdd: true,
          },
        },
      }),
    );

    // The command completes -> per-group outcomes render: imported...
    const importedCard = await screen.findByTestId('li-group-2');
    await waitFor(() =>
      expect(within(importedCard).getByText('Imported')).toBeInTheDocument(),
    );

    // ...and blocked, whose verbatim reasons open via the shared popover.
    const blockedCard = screen.getByTestId('li-group-4');
    await user.click(
      within(blockedCard).getByRole('button', { name: 'Bone — show reasons' }),
    );
    const popover = screen.getByRole('dialog', { name: 'Bone — show reasons' });
    const items = within(popover).getAllByRole('listitem');
    expect(items.map((li) => li.textContent)).toEqual([
      'Destination file already exists',
      'Format not allowed by profile',
    ]);
  });

  it('FRG-UI-015 — a group without a match is never included in the batch selection', async () => {
    const { fetcher } = fakeFetcher(
      makeResolver({ groups: () => [proposedGroup, noMatchGroup] }),
    );
    renderWithProviders(<LibraryImport />, { fetcher });

    await screen.findByTestId('li-group-3');
    // Only the matched group preselects: the batch counts 1, not 2.
    expect(
      await screen.findByRole('button', { name: 'Import 1 selected' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('checkbox', { name: 'Select Unknown Mini' }),
    ).not.toBeChecked();
  });
});
