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

/**
 * Command lifecycle payload carried by a `{name:'command', action:'updated'}`
 * message (backend/src/foragerr/ws/messages.py maps `CommandStatusChanged` to
 * `{id, name, status}`). All optional here because the bridge only reads it to
 * classify a message and must never throw on an unexpected shape.
 */
export interface CommandResource {
  id?: number;
  name?: string;
  status?: string;
}

/** The pull-refresh command name (backend `PULL_REFRESH_TRIGGERED_BY`). */
export const PULL_REFRESH_COMMAND = 'pull-refresh';

/**
 * True only for a `command` message that reports the pull-refresh command
 * reaching `completed` — the single command transition that rewrites this
 * week's stored pull entries. The backend pushes a `command` message on EVERY
 * lifecycle transition of EVERY command, so the bridge must NOT invalidate the
 * (expensive, whole-week) pull projection on all of them — only this one.
 */
export function isPullRefreshComplete(msg: WsMessage): boolean {
  if (msg.name !== 'command') return false;
  const r = msg.resource as Partial<CommandResource> | null;
  return !!r && r.name === PULL_REFRESH_COMMAND && r.status === 'completed';
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
