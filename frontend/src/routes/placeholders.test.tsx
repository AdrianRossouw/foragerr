import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../test/renderWithProviders';
import { fakeFetcher } from '../test/fakeFetcher';
import { LibraryIndexPlaceholder } from './placeholders';
import { mockSeriesList } from '../test/mockData';

/**
 * FRG-UI-001 — the placeholder route proves the architecture end to end: it mounts
 * the ['series'] query through the injected fetcher and renders its result. (Full
 * screens are out of scope for this scaffold pass.)
 */
describe('FRG-UI-001: placeholder route mounts a real query', () => {
  it('FRG-UI-001 — library placeholder issues the ["series"] query and renders the result', async () => {
    const { spy, fetcher } = fakeFetcher(() => mockSeriesList);
    renderWithProviders(<LibraryIndexPlaceholder />, { fetcher });

    await waitFor(() =>
      expect(screen.getByTestId('series-count')).toHaveTextContent('2 series'),
    );
    expect(spy).toHaveBeenCalledWith('/api/v1/series');
  });
});
