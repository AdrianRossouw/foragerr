import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../test/renderWithProviders';
import { createQueryClient } from '../queryClient';
import { makeFakeSocketFactory } from '../test/fakeSocket';
import type { Fetcher } from '../api/fetcher';
import type { StoreSourceResource } from '../api/types';
import { AppShell } from './AppShell';

/**
 * FRG-UI-023 — Scenario: Shell frames every route. Any route renders inside the
 * fixed frame (sidebar + global header + per-screen toolbar/content), and the
 * active nav item carries the accent treatment.
 */
function renderAt(path: string, body = 'ROUTE BODY') {
  const { factory } = makeFakeSocketFactory();
  return renderWithProviders(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell socketFactory={factory} />}>
          <Route path="/" element={<div>HOME BODY</div>} />
          <Route path="/queue" element={<div>{body}</div>} />
          <Route path="/wanted" element={<div>{body}</div>} />
          <Route path="/system/health" element={<div>{body}</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
    { withRouter: false, client: createQueryClient() },
  );
}

describe('FRG-UI-023: the shell frames every route', () => {
  it('FRG-UI-023 — sidebar, global header (search + icon buttons), and route content all render', () => {
    renderAt('/queue');

    // Sidebar nav + status footer.
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-status')).toBeInTheDocument();

    // Global header: relocated quick-search + health/system icon buttons.
    expect(screen.getByLabelText('Quick search your library')).toBeInTheDocument();
    expect(screen.getByTestId('header-health')).toBeInTheDocument();
    expect(screen.getByTestId('header-system')).toBeInTheDocument();

    // The routed screen renders inside the frame.
    expect(screen.getByText('ROUTE BODY')).toBeInTheDocument();
  });

  it('FRG-UI-023 — the active nav item carries the accent treatment', () => {
    renderAt('/wanted');
    const active = screen.getByRole('link', { name: /Wanted/ });
    expect(active.className).toMatch(/navLinkActive/);
    // A non-active item does not.
    expect(screen.getByRole('link', { name: /Queue/ }).className).not.toMatch(
      /navLinkActive/,
    );
  });

  it('FRG-UI-023 — the frame is present on a nested operator route too', () => {
    renderAt('/system/health');
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument();
    expect(screen.getByText('ROUTE BODY')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Health/ }).className).toMatch(
      /navLinkActive/,
    );
  });
});

/**
 * FRG-UI-029 — Scenario: Expiry surfaces globally. A connected source's expiry
 * raises the global banner AND tints the header health icon amber, from any
 * route in the shell.
 */
describe('FRG-UI-029: store-session expiry surfaces in the shell', () => {
  function expiredFetcher(): Fetcher {
    const sources: StoreSourceResource[] = [
      {
        id: 3,
        type: 'humble',
        name: 'Humble Bundle',
        connection_state: 'expired',
        auto_sync: false,
        last_sync_status: 'ok',
        settings: {},
      },
    ];
    const resolve = async (path: string): Promise<unknown> => {
      if (path === '/api/v1/sources') return sources;
      // Every other sidebar/shell read resolves empty so nothing throws.
      if (path.includes('/api/v1/series?')) {
        return { page: 1, pageSize: 200, sortKey: 's', sortDirection: 'asc', totalRecords: 0, records: [] };
      }
      if (path.includes('/api/v1/queue')) {
        return { page: 1, pageSize: 1, sortKey: 's', sortDirection: 'asc', totalRecords: 0, records: [] };
      }
      if (path === '/api/v1/health') return [];
      if (path.includes('/api/v1/system/status')) {
        return { version: '1.4.2', commit: 'x', build_date: '', config_dir: '', db_path: '', backups_dir: '', root_folder_count: 0, uptime_seconds: 0, python_version: '3.12', os: 'Linux' };
      }
      throw new Error(`unexpected path ${path}`);
    };
    return resolve as unknown as Fetcher;
  }

  it('FRG-UI-029 — the global banner appears and the header health icon turns amber', async () => {
    const { factory } = makeFakeSocketFactory();
    renderWithProviders(
      <MemoryRouter initialEntries={['/queue']}>
        <Routes>
          <Route element={<AppShell socketFactory={factory} />}>
            <Route path="/queue" element={<div>BODY</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
      { withRouter: false, client: createQueryClient(), fetcher: expiredFetcher() },
    );

    expect(await screen.findByTestId('global-store-banner')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId('header-health')).toHaveAttribute(
        'data-expired',
        'true',
      ),
    );
  });
});
