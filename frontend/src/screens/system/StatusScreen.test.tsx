import { describe, it, expect } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { makeSystemStatus } from '../../test/mockData';
import { StatusScreen } from './StatusScreen';

/**
 * FRG-UI-016 — System: Status screen. Renders GET /api/v1/system/status:
 * version/build info, managed `/config` paths, and runtime, with no secret
 * value rendered.
 */
describe('FRG-UI-016: system status screen', () => {
  it('FRG-UI-016 — Status screen shows version, paths, and runtime', async () => {
    const status = makeSystemStatus();
    const { spy, fetcher } = fakeFetcher(() => status);
    renderWithProviders(<StatusScreen />, { fetcher });

    const root = await screen.findByTestId('system-status');
    expect(spy).toHaveBeenCalledWith('/api/v1/system/status');

    expect(within(root).getByTestId('status-fact-Version')).toHaveTextContent(
      status.version,
    );
    expect(within(root).getByTestId('status-fact-Commit')).toHaveTextContent(
      status.commit,
    );
    expect(
      within(root).getByTestId('status-fact-Config Directory'),
    ).toHaveTextContent(status.config_dir);
    expect(within(root).getByTestId('status-fact-Database Path')).toHaveTextContent(
      status.db_path,
    );
    expect(
      within(root).getByTestId('status-fact-Backups Directory'),
    ).toHaveTextContent(status.backups_dir);
    expect(within(root).getByTestId('status-fact-Root Folders')).toHaveTextContent(
      String(status.root_folder_count),
    );
    expect(within(root).getByTestId('status-fact-Python')).toHaveTextContent(
      status.python_version,
    );
    expect(within(root).getByTestId('status-fact-OS')).toHaveTextContent(status.os);
  });

  it('FRG-UI-016 — Status screen renders no secret value (no provider key/credential field exists on the response)', async () => {
    const status = makeSystemStatus();
    const { fetcher } = fakeFetcher(() => status);
    renderWithProviders(<StatusScreen />, { fetcher });

    const root = await screen.findByTestId('system-status');
    // The contract (FRG-API-014) never carries a secret field; assert the
    // rendered DOM contains exactly the known safe fact set, nothing more.
    const facts = within(root)
      .getAllByTestId(/^status-fact-/)
      .map((el) => el.getAttribute('data-testid')?.replace('status-fact-', ''));
    expect(facts).toEqual([
      'Version',
      'Commit',
      'Build Date',
      'Config Directory',
      'Database Path',
      'Backups Directory',
      'Root Folders',
      'Uptime',
      'Python',
      'OS',
    ]);
  });
});
