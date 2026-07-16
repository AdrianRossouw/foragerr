import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../test/renderWithProviders';
import { fakeFetcher } from '../test/fakeFetcher';
import { App } from '../App';

/**
 * FRG-UI-036 — any route the SPA does not define renders the application shell
 * with a not-found screen linking back to the library, never a blank page
 * (M9 finding F3: `/settings/media` rendered fully blank).
 */
describe('FRG-UI-036: unknown routes render a not-found screen', () => {
  it('FRG-UI-036 — an undefined path renders the not-found screen inside the shell with a link home', async () => {
    // A tolerant fetcher: the shell chrome makes a few background reads (sources,
    // quick-search index, health) — resolve them all to empty so the shell mounts.
    const { fetcher } = fakeFetcher(() => []);
    renderWithProviders(<App />, { fetcher, route: '/settings/media' });

    const notFound = await screen.findByTestId('not-found');
    expect(notFound).toHaveTextContent('There is nothing at');
    expect(notFound).toHaveTextContent('/settings/media');
    const home = screen.getByRole('link', { name: 'Back to the library' });
    expect(home).toHaveAttribute('href', '/');
  });
});
