import type { SocketFactory, SocketLike } from '../ws/socket';

/**
 * A controllable fake socket for tests — no real WebSocket is ever opened. Each
 * `connect()` from the bridge produces a new FakeSocket; the harness drives
 * open/message/close manually to exercise invalidation, patching, and backoff.
 */
export class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((data: string) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  emitOpen(): void {
    this.onopen?.();
  }

  emitMessage(payload: unknown): void {
    this.onmessage?.(JSON.stringify(payload));
  }

  emitClose(): void {
    this.onclose?.();
  }

  emitError(): void {
    this.onerror?.();
  }

  close(): void {
    this.closed = true;
  }
}

/**
 * Returns a SocketFactory plus the list of sockets it has produced, newest last.
 * `factory.last()` is the socket the bridge is currently wired to.
 */
export function makeFakeSocketFactory(): {
  factory: SocketFactory;
  sockets: FakeSocket[];
  last: () => FakeSocket;
} {
  const sockets: FakeSocket[] = [];
  const factory: SocketFactory = () => {
    const s = new FakeSocket();
    sockets.push(s);
    return s;
  };
  return { factory, sockets, last: () => sockets[sockets.length - 1] };
}
