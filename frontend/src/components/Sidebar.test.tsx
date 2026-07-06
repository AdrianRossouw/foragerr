import { describe, it, expect } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '../test/renderWithProviders';
import { Sidebar } from './Sidebar';

/**
 * FRG-UI-016 — nav reachability: the System area (Status / Health / Tasks)
 * is reachable from the sidebar as its own group, alongside the existing
 * Settings/Activity groups (Sonarr-shaped nav).
 */
describe('FRG-UI-016: System nav group', () => {
  it('FRG-UI-016 — the sidebar exposes a System group linking to Status, Health, and Tasks', () => {
    renderWithProviders(<Sidebar />, { withRouter: true });

    const group = screen.getByText('System').closest('nav');
    expect(group).not.toBeNull();

    expect(
      within(group as HTMLElement).getByRole('link', { name: 'Status' }),
    ).toHaveAttribute('href', '/system/status');
    expect(
      within(group as HTMLElement).getByRole('link', { name: 'Health' }),
    ).toHaveAttribute('href', '/system/health');
    expect(
      within(group as HTMLElement).getByRole('link', { name: 'Tasks' }),
    ).toHaveAttribute('href', '/system/tasks');
  });
});
