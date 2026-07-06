import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { createQueryClient } from '../queryClient';
import { FetcherProvider } from '../api/fetcher';
import {
  useCommandStatus,
  useHistoryPage,
  useSeriesDetail,
  useSeriesList,
  useQueuePage,
} from '../api/hooks';
import { queryKeys } from '../api/queryKeys';
import type { QueueItem } from '../api/types';
import { WebSocketBridge } from './WebSocketBridge';
import { useConnectionStore } from './connectionStore';
import { makeFakeSocketFactory } from '../test/fakeSocket';
import { fakeFetcher } from '../test/fakeFetcher';
import { makeCommand, mockSeriesList, mockQueuePage1, pageOf } from '../test/mockData';

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

  it('FRG-UI-001 — a queue-progress tick without numeric progress/sizeLeft preserves the row values; a non-numeric tick is rejected and invalidates instead', async () => {
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

    // A status-only tick (no progress/sizeLeft): patch in place, preserving the
    // row's existing numbers — never blanking them into "undefined%".
    act(() =>
      last().emitMessage({
        name: 'queue',
        action: 'progress',
        resource: { id: 900, page: 1 },
      }),
    );
    const patched = client.getQueryData<QueueItem[]>(queryKeys.queue.page(1));
    const row = patched?.find((i) => i.id === 900);
    expect(row?.progress).toBe(10); // preserved, not undefined
    expect(row?.sizeLeft).toBe(90); // preserved, not undefined
    expect(spy).toHaveBeenCalledTimes(1); // still a patch, no refetch

    // A malformed tick (non-numeric progress) fails the guard and is treated as
    // a plain queue invalidation → the active page refetches.
    act(() =>
      last().emitMessage({
        name: 'queue',
        action: 'progress',
        resource: { id: 900, page: 1, progress: 'oops' },
      }),
    );
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });

  it('FRG-UI-001 — a series message carrying an id invalidates that detail plus the list, not the whole prefix', async () => {
    const client = createQueryClient();
    const { spy, fetcher } = fakeFetcher(() => mockSeriesList);
    const { factory, last } = makeFakeSocketFactory();

    function Harness() {
      useSeriesList(); // ['series']
      useSeriesDetail(5); // ['series', 5]
      return <WebSocketBridge socketFactory={factory} />;
    }

    render(
      <QueryClientProvider client={client}>
        <FetcherProvider fetcher={fetcher}>
          <Harness />
        </FetcherProvider>
      </QueryClientProvider>,
    );

    // Both observers make their initial fetch.
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));

    act(() => last().emitOpen());
    act(() =>
      last().emitMessage({ name: 'series', action: 'updated', resource: { id: 5 } }),
    );

    // The list and the id-5 detail both refetch (id-scoped invalidation).
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(4));
    expect(spy).toHaveBeenCalledWith('/api/v1/series');
    expect(spy).toHaveBeenCalledWith('/api/v1/series/5');
  });

  it('FRG-UI-001 — a queue updated message invalidates ["queue"] and the queue query refetches', async () => {
    const client = createQueryClient();
    const { spy, fetcher } = fakeFetcher(() => mockQueuePage1);
    const { factory, last } = makeFakeSocketFactory();

    function Harness() {
      useQueuePage(1); // active observer of ['queue', 1]
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
    // The backend's invalidation signal (backend/src/foragerr/ws/messages.py):
    // NOT a progress patch — no page/progress fields on the resource.
    act(() =>
      last().emitMessage({
        name: 'queue',
        action: 'updated',
        resource: { downloadId: 'SABnzbd_nzo_900', status: 'imported', health: 'ok' },
      }),
    );

    // Refetch observed — invalidation, not an in-place patch.
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(spy).toHaveBeenLastCalledWith('/api/v1/queue?page=1');
  });

  it('FRG-UI-001 — a queue updated push no longer piggybacks history (dedicated pushes own it)', async () => {
    const client = createQueryClient();
    const { spy, fetcher } = fakeFetcher((path) =>
      String(path).startsWith('/api/v1/history')
        ? pageOf([], { pageSize: 20 })
        : mockQueuePage1,
    );
    const { factory, last } = makeFakeSocketFactory();

    function Harness() {
      useQueuePage(1); // ['queue', 1]
      useHistoryPage(1); // ['history', 1, …]
      return <WebSocketBridge socketFactory={factory} />;
    }

    render(
      <QueryClientProvider client={client}>
        <FetcherProvider fetcher={fetcher}>
          <Harness />
        </FetcherProvider>
      </QueryClientProvider>,
    );

    // Both observers make their initial fetch.
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));

    act(() => last().emitOpen());
    act(() =>
      last().emitMessage({
        name: 'queue',
        action: 'updated',
        resource: { downloadId: 'SABnzbd_nzo_900', status: 'imported' },
      }),
    );

    // The queue page refetches…
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/queue?page=1'),
    );
    // …but history is NOT re-invalidated by a queue push: still one call.
    const historyCalls = spy.mock.calls.filter(([p]) =>
      String(p).startsWith('/api/v1/history'),
    );
    expect(historyCalls).toHaveLength(1);
  });

  it('FRG-UI-001 — a command updated message invalidates ["command", id] and the status query refetches', async () => {
    const client = createQueryClient();
    const { spy, fetcher } = fakeFetcher(() =>
      makeCommand({ id: 55, status: 'completed' }),
    );
    const { factory, last } = makeFakeSocketFactory();

    function Harness() {
      useCommandStatus(55); // active observer of ['command', 55]
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
        name: 'command',
        action: 'updated',
        resource: { id: 55, name: 'refresh-series', status: 'completed' },
      }),
    );

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
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
