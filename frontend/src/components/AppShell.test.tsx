import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../test/renderWithProviders';
import { createQueryClient } from '../queryClient';
import { makeFakeSocketFactory } from '../test/fakeSocket';
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
