import { type ReactElement, type ReactNode } from 'react';
import { render } from '@testing-library/react';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { createQueryClient } from '../queryClient';
import { FetcherProvider, type Fetcher } from '../api/fetcher';

interface Options {
  client?: QueryClient;
  fetcher?: Fetcher;
  route?: string;
  withRouter?: boolean;
}

/**
 * Renders UI with the same provider stack as the app, but with an injectable fake
 * fetcher and an isolated QueryClient per test.
 */
export function renderWithProviders(
  ui: ReactElement,
  { client, fetcher, route = '/', withRouter = true }: Options = {},
) {
  const queryClient = client ?? createQueryClient();
  const noopFetcher: Fetcher = async () => {
    throw new Error('fetcher not provided to test');
  };

  const Wrapper = ({ children }: { children: ReactNode }) => {
    const inner = (
      <QueryClientProvider client={queryClient}>
        <FetcherProvider fetcher={fetcher ?? noopFetcher}>{children}</FetcherProvider>
      </QueryClientProvider>
    );
    return withRouter ? (
      <MemoryRouter initialEntries={[route]}>{inner}</MemoryRouter>
    ) : (
      inner
    );
  };

  return { ...render(ui, { wrapper: Wrapper }), client: queryClient };
}
