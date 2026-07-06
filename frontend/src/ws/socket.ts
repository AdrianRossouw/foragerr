/*
 * Minimal socket abstraction (FRG-UI-001).
 *
 * The WebSocketBridge depends on this interface, not the global WebSocket, so
 * tests can inject a FAKE socket and drive open/message/close deterministically.
 * The default factory wraps the real browser WebSocket.
 */
export interface SocketLike {
  close(): void;
  onopen: (() => void) | null;
  onclose: (() => void) | null;
  onmessage: ((data: string) => void) | null;
  onerror: (() => void) | null;
}

export type SocketFactory = (url: string) => SocketLike;

/**
 * Resolve a possibly-relative WS path to an absolute ws(s):// URL derived from
 * the page origin. Relying on the browser's relative-URL support for the raw
 * WebSocket constructor is fragile; building the absolute URL explicitly picks
 * `wss:` under HTTPS and `ws:` otherwise, against the current host.
 */
export function toAbsoluteWsUrl(url: string): string {
  if (/^wss?:\/\//i.test(url)) return url;
  const scheme = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
  const path = url.startsWith('/') ? url : `/${url}`;
  return `${scheme}${window.location.host}${path}`;
}

export const defaultSocketFactory: SocketFactory = (url: string): SocketLike => {
  const ws = new WebSocket(toAbsoluteWsUrl(url));
  const adapter: SocketLike = {
    close: () => ws.close(),
    onopen: null,
    onclose: null,
    onmessage: null,
    onerror: null,
  };
  ws.addEventListener('open', () => adapter.onopen?.());
  ws.addEventListener('close', () => adapter.onclose?.());
  ws.addEventListener('error', () => adapter.onerror?.());
  ws.addEventListener('message', (ev: MessageEvent) =>
    adapter.onmessage?.(typeof ev.data === 'string' ? ev.data : String(ev.data)),
  );
  return adapter;
};
