// design-sync preview provider (not part of the app build). Wraps preview
// renders in the same context stack main.tsx gives the real SPA — router +
// react-query + fetcher — so context-reading components (Sidebar, AppShell,
// HeaderQuickSearch, LogoutButton, GlobalBanner) render in cards. The fetcher
// is a stub resolving to empty data: previews must never issue network
// requests. Wired via extraEntries + provider in .design-sync/config.json;
// excluded from the component list via componentSrcMap.
import { useMemo } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FetcherProvider } from '../frontend/src/api/fetcher';

const previewQueryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: Infinity } },
});

// Empty-but-shaped responses: array-ish endpoints get [], everything else {}.
const stubFetcher = async (path) =>
  /\b(items|series|issues|results|list|sources|indexers|providers|queue|history|wanted|blocklist|creators|follows|notifications|banners)\b/.test(
    path,
  )
    ? []
    : {};

export function PreviewProvider({ children }) {
  return (
    <MemoryRouter>
      <QueryClientProvider client={previewQueryClient}>
        <FetcherProvider fetcher={stubFetcher}>
          {/* Preview cards render on the harness's white page, but every
              foragerr component is designed for the dark app surface (in the
              real SPA body carries --surface-page). Reproduce that context so
              translucent tints and light text read the way they do in the app. */}
          <div
            style={{
              background: 'var(--surface-page)',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-family-base)',
              fontSize: 'var(--font-size-base)',
              padding: 16,
              minHeight: '100%',
              boxSizing: 'border-box',
            }}
          >
            {children}
          </div>
        </FetcherProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
}

// Fixture scope for previews of data-reading components (GlobalBanner,
// Sidebar, HeaderQuickSearch, provider settings): nests a fresh query client
// + fetcher whose responses come from the `responses` map (first key the
// request path contains, substring match), falling back to the empty stub.
export function PreviewData({ responses = {}, children }) {
  const client = useMemo(
    () => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } }),
    [],
  );
  const fetcher = async (path) => {
    for (const [key, value] of Object.entries(responses)) if (path.includes(key)) return value;
    return stubFetcher(path);
  };
  return (
    <QueryClientProvider client={client}>
      <FetcherProvider fetcher={fetcher}>{children}</FetcherProvider>
    </QueryClientProvider>
  );
}
