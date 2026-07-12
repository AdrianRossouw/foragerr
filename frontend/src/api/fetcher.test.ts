import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defaultFetcher, ApiRequestError } from './fetcher';
import { useAuthStore } from '../store/authStore';

/**
 * FRG-AUTH-010 — the API client's central 401 interception: any endpoint
 * OTHER than the three auth endpoints themselves (login/logout/me) 401ing
 * mid-session means the session died, so the client-side auth store must flip
 * to `unauthenticated` (AuthGate observes this and redirects). The three auth
 * endpoints own their own 401 handling and must NOT also flip the store here —
 * that is exactly what would produce a redirect loop off the login screen's
 * own "wrong password" response.
 */
function mockFetchOnce(status: number, body: unknown = {}): void {
  const ok = status >= 200 && status < 300;
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok,
      status,
      json: async () => body,
    }),
  );
}

describe('FRG-AUTH-010: defaultFetcher 401 interception', () => {
  beforeEach(() => {
    useAuthStore.setState({ status: 'authenticated', username: 'adrian' });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('FRG-AUTH-010: a 401 from an ordinary API endpoint flips the auth store to unauthenticated', async () => {
    mockFetchOnce(401, { detail: 'invalid credentials' });
    await expect(defaultFetcher('/api/v1/queue')).rejects.toBeInstanceOf(ApiRequestError);
    expect(useAuthStore.getState().status).toBe('unauthenticated');
  });

  it('FRG-AUTH-010: a 401 from POST /api/v1/auth/login does NOT flip the store (the form owns this failure)', async () => {
    mockFetchOnce(401, { detail: 'invalid credentials' });
    await expect(
      defaultFetcher('/api/v1/auth/login', { method: 'POST', body: {} }),
    ).rejects.toBeInstanceOf(ApiRequestError);
    expect(useAuthStore.getState().status).toBe('authenticated');
  });

  it('FRG-AUTH-010: a 401 from GET /api/v1/auth/me does NOT flip the store (AuthGate owns this path)', async () => {
    mockFetchOnce(401, {});
    await expect(defaultFetcher('/api/v1/auth/me')).rejects.toBeInstanceOf(ApiRequestError);
    expect(useAuthStore.getState().status).toBe('authenticated');
  });

  it('FRG-AUTH-010: a 401 from POST /api/v1/auth/logout does NOT flip the store', async () => {
    mockFetchOnce(401, {});
    await expect(
      defaultFetcher('/api/v1/auth/logout', { method: 'POST' }),
    ).rejects.toBeInstanceOf(ApiRequestError);
    expect(useAuthStore.getState().status).toBe('authenticated');
  });

  it('FRG-AUTH-010: a non-401 failure leaves the auth store untouched', async () => {
    mockFetchOnce(500, {});
    await expect(defaultFetcher('/api/v1/queue')).rejects.toBeInstanceOf(ApiRequestError);
    expect(useAuthStore.getState().status).toBe('authenticated');
  });

  it('FRG-AUTH-010: every request carries same-origin credentials so the session cookie rides along', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchSpy);
    await defaultFetcher('/api/v1/series');
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/series',
      expect.objectContaining({ credentials: 'same-origin' }),
    );
  });
});
