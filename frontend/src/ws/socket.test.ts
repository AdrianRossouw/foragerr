import { describe, it, expect } from 'vitest';
import { toAbsoluteWsUrl } from './socket';

/*
 * FRG-UI-001 — the socket factory must not rely on relative-URL support in the
 * WebSocket constructor: a relative path is resolved to an absolute ws(s):// URL
 * against the current origin, and an already-absolute URL passes through.
 */
describe('FRG-UI-001: WebSocket URL resolution', () => {
  it('FRG-UI-001 — a relative path resolves to an absolute ws:// URL on the page host', () => {
    const resolved = toAbsoluteWsUrl('/api/v1/ws');
    expect(resolved.startsWith('ws://') || resolved.startsWith('wss://')).toBe(true);
    expect(resolved.endsWith('/api/v1/ws')).toBe(true);
    expect(resolved).toContain(window.location.host);
    // Matches the page scheme (jsdom serves http -> ws).
    const scheme = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    expect(resolved).toBe(`${scheme}${window.location.host}/api/v1/ws`);
  });

  it('FRG-UI-001 — an already-absolute ws(s):// URL is returned unchanged', () => {
    expect(toAbsoluteWsUrl('wss://example.test/socket')).toBe(
      'wss://example.test/socket',
    );
    expect(toAbsoluteWsUrl('ws://example.test:9/ws')).toBe('ws://example.test:9/ws');
  });
});
