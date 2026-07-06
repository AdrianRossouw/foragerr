import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../api/queryKeys';
import type { QueueItem } from '../api/types';
import { useConnectionStore } from './connectionStore';
import {
  defaultSocketFactory,
  type SocketFactory,
  type SocketLike,
} from './socket';
import { isQueueProgress, parseWsMessage, type WsMessage } from './messages';

export interface WebSocketBridgeProps {
  url?: string;
  socketFactory?: SocketFactory;
  /** Base reconnect delay in ms (doubled each attempt, capped at maxBackoffMs). */
  baseBackoffMs?: number;
  maxBackoffMs?: number;
  /** Test hook: invoked with the scheduled delay + attempt number on each retry. */
  onReconnectScheduled?: (delayMs: number, attempt: number) => void;
}

/**
 * WebSocketBridge (FRG-UI-001).
 *
 * The SINGLE place server-push messages touch client state. It maps
 * {name, action, resource} messages onto React Query cache operations:
 *   - a `series` message invalidates ['series'] (active queries refetch);
 *   - a queue-progress message PATCHES the cached ['queue', page] entry in place
 *     with NO new request (no backend emitter in M1; byte-level ticks are M2);
 *   - any other `queue` message (the backend's `{name:'queue', action:'updated'}`
 *     invalidation signal — see backend/src/foragerr/ws/messages.py) invalidates
 *     the ['queue'] prefix so active queue pages refetch. It no longer
 *     piggy-backs history/wanted/blocklist: those families now have their OWN
 *     dedicated pushes (below), so inferring them from queue transitions would
 *     double-invalidate and still miss push-less writers;
 *   - dedicated `history`/`wanted`/`blocklist` messages (m2-daily-surfaces: the
 *     backend emits `history` on every history event, `wanted` when file
 *     presence changes, `blocklist` on blocklist writes) invalidate their family;
 *   - a `command` message invalidates the ['command'] prefix (status pushes).
 * It reconnects on an increasing backoff and reflects connection state in the
 * shared store (rendered by the sidebar footer). It holds no server data itself.
 */
export function WebSocketBridge({
  url = '/api/v1/ws',
  socketFactory = defaultSocketFactory,
  baseBackoffMs = 1000,
  maxBackoffMs = 30000,
  onReconnectScheduled,
}: WebSocketBridgeProps): null {
  const queryClient = useQueryClient();
  const setStatus = useConnectionStore((s) => s.setStatus);

  // Refs so the connect closure is stable across renders and reconnects.
  const socketRef = useRef<SocketLike | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const disposedRef = useRef(false);

  useEffect(() => {
    disposedRef.current = false;

    const applyMessage = (msg: WsMessage): void => {
      if (isQueueProgress(msg)) {
        const { id, page, progress, sizeLeft, status } = msg.resource;
        // Patch in place — setQueryData never issues a network request. Absent
        // fields fall back to the row's existing values (a status-only tick must
        // not blank out progress/sizeLeft into "undefined%").
        queryClient.setQueryData<QueueItem[]>(queryKeys.queue.page(page), (prev) =>
          prev?.map((item) =>
            item.id === id
              ? {
                  ...item,
                  progress: progress ?? item.progress,
                  sizeLeft: sizeLeft ?? item.sizeLeft,
                  status: status ?? item.status,
                }
              : item,
          ),
        );
        return;
      }
      if (msg.name === 'queue') {
        // Non-progress queue push (`action:'updated'`) is an INVALIDATION
        // signal — the backend has no page/progress fields to patch with;
        // refetch the queue pages. History/Wanted/Blocklist are NOT inferred
        // here: each has its own dedicated push (below), which also covers the
        // writers a queue transition never sees (e.g. manual file deletes).
        void queryClient.invalidateQueries({ queryKey: queryKeys.queue.all() });
        return;
      }
      // Dedicated family pushes (m2-daily-surfaces): each invalidates exactly
      // its family. The backend emits `history` on every history event,
      // `wanted` when an issue's file presence changes, and `blocklist` on
      // blocklist writes.
      if (msg.name === 'history') {
        void queryClient.invalidateQueries({ queryKey: queryKeys.history.all() });
        return;
      }
      if (msg.name === 'wanted') {
        void queryClient.invalidateQueries({ queryKey: queryKeys.wanted.all() });
        return;
      }
      if (msg.name === 'blocklist') {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.blocklist.all(),
        });
        return;
      }
      if (msg.name === 'series') {
        // When the push carries a series id, invalidate that detail exactly plus
        // the series list — not the whole ['series'] prefix — so unrelated detail
        // queries are not refetched. An id-less push falls back to the broad
        // invalidation. Active observers refetch; no manual refetch in any screen.
        const id = (msg.resource as { id?: unknown } | null)?.id;
        if (typeof id === 'number') {
          void queryClient.invalidateQueries({ queryKey: queryKeys.series.detail(id) });
          void queryClient.invalidateQueries({
            queryKey: queryKeys.series.all(),
            exact: true,
          });
        } else {
          void queryClient.invalidateQueries({ queryKey: queryKeys.series.all() });
        }
        return;
      }
      if (msg.name === 'command') {
        void queryClient.invalidateQueries({ queryKey: queryKeys.command.all() });
      }
    };

    const scheduleReconnect = (): void => {
      if (disposedRef.current) return;
      attemptRef.current += 1;
      const delay = Math.min(
        baseBackoffMs * 2 ** (attemptRef.current - 1),
        maxBackoffMs,
      );
      onReconnectScheduled?.(delay, attemptRef.current);
      timerRef.current = setTimeout(connect, delay);
    };

    function connect(): void {
      if (disposedRef.current) return;
      setStatus('connecting');
      const socket = socketFactory(url);
      socketRef.current = socket;

      socket.onopen = () => {
        attemptRef.current = 0;
        setStatus('connected');
      };
      socket.onmessage = (data) => {
        const msg = parseWsMessage(data);
        if (msg) applyMessage(msg);
      };
      socket.onclose = () => {
        if (disposedRef.current) return;
        setStatus('disconnected');
        scheduleReconnect();
      };
      socket.onerror = () => {
        // Errors are followed by close; surface disconnected immediately.
        setStatus('disconnected');
      };
    }

    connect();

    return () => {
      disposedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [
    url,
    socketFactory,
    baseBackoffMs,
    maxBackoffMs,
    onReconnectScheduled,
    queryClient,
    setStatus,
  ]);

  return null;
}
