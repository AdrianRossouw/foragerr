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

export const defaultSocketFactory: SocketFactory = (url: string): SocketLike => {
  const ws = new WebSocket(url);
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
