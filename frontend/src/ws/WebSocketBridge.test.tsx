import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { createQueryClient } from '../queryClient';
import { FetcherProvider } from '../api/fetcher';
import { useSeriesList, useQueuePage } from '../api/hooks';
import { queryKeys } from '../api/queryKeys';
import type { QueueItem } from '../api/types';
import { WebSocketBridge } from './WebSocketBridge';
import { useConnectionStore } from './connectionStore';
import { makeFakeSocketFactory } from '../test/fakeSocket';
import { fakeFetcher } from '../test/fakeFetcher';
import { mockSeriesList, mockQueuePage1 } from '../test/mockData';

beforeEach(() => {
  // Reset the shared connection store between cases (module singleton).
  useConnectionStore.setState({ status: 'connecting' });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('FRG-UI-001: WebSocketBridge maps messages to cache operations', () => {
  it('FRG-UI-001 — a series message invalidates ["series"] and a refetch is observed', async () => {
    const client = createQueryClient();
    const { spy, fetcher } = fakeFetcher(() => mockSeriesList);
    const { factory, last } = makeFakeSocketFactory();

    function Harness() {
      useSeriesList(); // active observer of ['series']
      return <WebSocketBridge socketFactory={factory} />;
    }

    render(
      <QueryClientProvider client={client}>
        <FetcherProvider fetcher={fetcher}>
          <Harness />
        </FetcherProvider>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    act(() => last().emitOpen());
    act(() =>
      last().emitMessage({ name: 'series', action: 'updated', resource: { id: 1 } }),
    );

    // Refetch observed — no manual refetch call exists in any screen component.
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });

  it('FRG-UI-001 — a queue-progress message patches ["queue", page] in place with no new request', async () => {
    const client = createQueryClient();
    const { spy, fetcher } = fakeFetcher(() => mockQueuePage1);
    const { factory, last } = makeFakeSocketFactory();

    function Harness() {
      useQueuePage(1); // seeds ['queue', 1]
      return <WebSocketBridge socketFactory={factory} />;
    }

    render(
      <QueryClientProvider client={client}>
        <FetcherProvider fetcher={fetcher}>
          <Harness />
        </FetcherProvider>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    act(() => last().emitOpen());
    act(() =>
      last().emitMessage({
        name: 'queue',
        action: 'progress',
        resource: { id: 900, page: 1, progress: 80, sizeLeft: 20 },
      }),
    );

    const patched = client.getQueryData<QueueItem[]>(queryKeys.queue.page(1));
    expect(patched?.find((i) => i.id === 900)?.progress).toBe(80);
    expect(patched?.find((i) => i.id === 900)?.sizeLeft).toBe(20);
    // Untouched row is unchanged.
    expect(patched?.find((i) => i.id === 901)?.progress).toBe(25);
    // No refetch was triggered by the patch.
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('FRG-UI-001 — reconnect uses increasing backoff and the sidebar footer reflects connection state', async () => {
    vi.useFakeTimers();
    const client = createQueryClient();
    const { fetcher } = fakeFetcher(() => mockSeriesList);
    const { factory, sockets } = makeFakeSocketFactory();
    const delays: number[] = [];

    // Sidebar is imported lazily-free; render it with the bridge under a router.
    const { Sidebar } = await import('../components/Sidebar');

    render(
      <QueryClientProvider client={client}>
        <FetcherProvider fetcher={fetcher}>
          <MemoryRouter>
            <Sidebar />
            <WebSocketBridge
              socketFactory={factory}
              baseBackoffMs={1000}
              maxBackoffMs={30000}
              onReconnectScheduled={(delay) => delays.push(delay)}
            />
          </MemoryRouter>
        </FetcherProvider>
      </QueryClientProvider>,
    );

    const footer = () => screen.getByTestId('connection-status');

    // First socket opens -> connected.
    act(() => sockets[0].emitOpen());
    expect(footer()).toHaveTextContent('Connected');

    // Drops -> disconnected + backoff attempt #1 (1000ms).
    act(() => sockets[0].emitClose());
    expect(footer()).toHaveTextContent('Disconnected');
    expect(delays).toEqual([1000]);

    // Advance to reconnect; second socket drops -> backoff attempt #2 (2000ms).
    act(() => vi.advanceTimersByTime(1000));
    expect(sockets).toHaveLength(2);
    act(() => sockets[1].emitClose());
    expect(delays).toEqual([1000, 2000]); // strictly increasing

    // Advance to reconnect; third socket opens -> connected again.
    act(() => vi.advanceTimersByTime(2000));
    expect(sockets).toHaveLength(3);
    act(() => sockets[2].emitOpen());
    expect(footer()).toHaveTextContent('Connected');
  });

  it('FRG-UI-001 — no server data is held in a client store outside React Query', () => {
    // The only client store touching the WS path holds connection status, not
    // server resources. Guards the "no component holds server data outside React
    // Query" clause.
    const state = useConnectionStore.getState();
    expect(Object.keys(state).sort()).toEqual(['setStatus', 'status']);
    expect(typeof state.status).toBe('string');
  });
});
