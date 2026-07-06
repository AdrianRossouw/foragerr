import type { QueueItem } from '../api/types';

/*
 * WebSocket push message shape (FRG-UI-001): {name, action, resource}.
 *   name     — resource family, e.g. 'series' | 'queue'
 *   action   — 'updated' | 'progress' | ...
 *   resource — the payload (a partial resource or progress record)
 */
export interface WsMessage {
  name: string;
  action: string;
  resource: unknown;
}

/**
 * Progress payload carried by a `{name:'queue', action:'progress'}` message.
 * `progress`/`sizeLeft` are OPTIONAL: a tick may carry only a status transition,
 * in which case the bridge preserves the row's existing numeric values.
 */
export interface QueueProgressResource {
  id: number;
  page: number;
  progress?: number;
  sizeLeft?: number;
  status?: QueueItem['status'];
}

export function isQueueProgress(msg: WsMessage): msg is WsMessage & {
  resource: QueueProgressResource;
} {
  if (msg.name !== 'queue' || msg.action !== 'progress') return false;
  const r = msg.resource as Partial<QueueProgressResource> | null;
  if (!r || typeof r.id !== 'number' || typeof r.page !== 'number') return false;
  // When present, progress/sizeLeft MUST be numbers — otherwise a malformed
  // tick would render "undefined%" once patched into the cached row.
  if (r.progress !== undefined && typeof r.progress !== 'number') return false;
  if (r.sizeLeft !== undefined && typeof r.sizeLeft !== 'number') return false;
  return true;
}

export function parseWsMessage(raw: string): WsMessage | null {
  try {
    const parsed = JSON.parse(raw) as Partial<WsMessage>;
    if (typeof parsed.name === 'string' && typeof parsed.action === 'string') {
      return { name: parsed.name, action: parsed.action, resource: parsed.resource };
    }
    return null;
  } catch {
    return null;
  }
}
