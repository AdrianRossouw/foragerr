import { request as pwRequest, type APIRequestContext } from '@playwright/test';

/**
 * Auth fixtures (m8-auth-core, FRG-AUTH-002/010). The whole stack now enforces
 * mandatory authentication: every surface refuses a bare request. These are the
 * FIXED, non-secret test credentials the hermetic stack bootstraps with — a
 * throwaway admin account seeded from compose env, never real secrets. run.sh
 * and compose.yaml carry the same defaults; the browser projects reach the app
 * with a saved session (see auth.setup.ts / playwright.config.ts), and the
 * programmatic API contexts below reach it with the bootstrap API key.
 */
export const ADMIN_USER = process.env.FORAGERR_ADMIN_USER ?? 'e2e-admin';
export const ADMIN_PASSWORD =
  process.env.FORAGERR_ADMIN_PASSWORD ?? 'e2e-admin-pw-9c3f2a1b';

/**
 * The LIVE admin/OPDS passwords, accounting for zzz-credential-lifecycle.spec.ts
 * rotating both away from the bootstrap constants above. That file threads its
 * final values through these env vars at the point each rotation is confirmed
 * (mirroring the existing `E2E_API_KEY` threading for key rotation) — a spec
 * that runs after it (only zzzz-rate-audit.spec.ts, by design) must call these
 * functions rather than read `ADMIN_PASSWORD` directly, since the constant is
 * only correct for specs that run BEFORE the rotation. Functions, not
 * top-level consts: the env var is only populated once that spec's test body
 * actually executes, long after every module has already loaded.
 */
export function currentAdminPassword(): string {
  return process.env.E2E_CURRENT_ADMIN_PASSWORD ?? ADMIN_PASSWORD;
}
export function currentOpdsPassword(): string {
  return process.env.E2E_CURRENT_OPDS_PASSWORD ?? ADMIN_PASSWORD;
}

/** Where auth.setup.ts writes the authenticated browser session (gitignored). */
export const STORAGE_STATE = '.auth/state.json';

/**
 * A programmatic API context authenticated with the bootstrap API key.
 *
 * The API key surface (``X-Api-Key`` header) is the clean path for a non-browser
 * caller: it is exempt from the cookie surface's CSRF Origin check, so an
 * unsafe method (POST/PUT/DELETE) needs no Origin header threaded through. The
 * raw key is surfaced ONCE at bootstrap; run.sh retrieves it and exports it as
 * ``E2E_API_KEY`` for every spec. The key is stored SHA-256 in the DB (on the
 * persisted /config volume), so the same value keeps working across the
 * restart/recreate the zz-* specs perform — no per-port re-auth needed.
 *
 * ``storageState`` is pinned EMPTY on purpose: an ``APIRequestContext`` created
 * inside a project inherits that project's ``use.storageState`` (the saved
 * login cookie), which would make these contexts authenticate by COOKIE instead
 * of the key — and a cookie-authed unsafe method then trips the CSRF Origin
 * check (403). Forcing an empty jar guarantees the ONLY credential is the key.
 */
export const EMPTY_STORAGE_STATE: { cookies: []; origins: [] } = {
  cookies: [],
  origins: [],
};

export async function newApiContext(baseURL: string): Promise<APIRequestContext> {
  const apiKey = process.env.E2E_API_KEY;
  if (!apiKey) {
    throw new Error(
      'E2E_API_KEY is not set — the authenticated API context needs the ' +
        'bootstrap API key that run.sh retrieves. Run the suite via e2e/run.sh.',
    );
  }
  return pwRequest.newContext({
    baseURL,
    ignoreHTTPSErrors: true,
    storageState: EMPTY_STORAGE_STATE,
    extraHTTPHeaders: { 'X-Api-Key': apiKey },
  });
}

/**
 * A genuinely UNAUTHENTICATED API context (no cookie, no key). Same
 * empty-storageState pin as above — without it the context would inherit the
 * project's login cookie and stop being "bare". Used by the negative-path spec
 * to prove the perimeter refuses credential-free requests.
 */
export async function newBareContext(baseURL: string): Promise<APIRequestContext> {
  return pwRequest.newContext({
    baseURL,
    ignoreHTTPSErrors: true,
    storageState: EMPTY_STORAGE_STATE,
  });
}

/** Enabled providers pointing at mockhub (resolved inside the compose network).
 *  Idempotent: safe to call again on a serial-group retry.
 *
 *  NOTE (FRG-DEP-013): the app now seeds a default "GetComics" indexer + a
 *  "GetComics" DDL download-client on first run, so an e2e run carries a
 *  DUPLICATE getcomics provider alongside the 'mock-getcomics' one created here.
 *  Assertions over the provider lists must therefore stay EXISTENTIAL (match by
 *  name / .some(), never exact counts). The seeded row is neutral only because
 *  the compose `getcomics.org` -> mockhub alias (compose.yaml:81) keeps its
 *  https://getcomics.org base_url inside the hermetic network. */
export async function createProviders(api: APIRequestContext): Promise<void> {
  const indexers = await (await api.get('/api/v1/indexer')).json();
  const names = new Set((indexers as any[]).map((i) => i.name));

  if (!names.has('mock-newznab')) {
    await expectOk(
      api.post('/api/v1/indexer', {
        data: {
          name: 'mock-newznab',
          implementation: 'newznab',
          settings: {
            base_url: 'http://mockhub:8080/newznab',
            api_key: 'e2e-example' /* dummy fixture value, not a secret */,
            categories: [7030],
          },
          enabled: true,
        },
      }),
      'create newznab indexer',
    );
  }

  if (!names.has('mock-getcomics')) {
    await expectOk(
      api.post('/api/v1/indexer', {
        data: {
          name: 'mock-getcomics',
          implementation: 'getcomics',
          settings: {
            base_url: 'https://getcomics.org',
            min_interval_seconds: 1,
            max_pages: 1,
          },
          enabled: true,
        },
      }),
      'create getcomics indexer',
    );
  }

  const clients = await (await api.get('/api/v1/downloadclient')).json();
  if (!(clients as any[]).some((c) => c.name === 'builtin-ddl')) {
    await expectOk(
      api.post('/api/v1/downloadclient', {
        data: {
          name: 'builtin-ddl',
          implementation: 'ddl',
          settings: {
            host_priority: 'main,mirror,pixeldrain,mediafire,mega',
            prefer_upscaled: true,
          },
          enabled: true,
        },
      }),
      'create ddl download client',
    );
  }
}

async function expectOk(p: ReturnType<APIRequestContext['post']>, what: string) {
  const res = await p;
  if (!res.ok()) {
    throw new Error(`${what} failed: HTTP ${res.status()} ${await res.text()}`);
  }
  return res;
}

/** Poll ``fn`` until it returns truthy or ``timeoutMs`` elapses. */
export async function until<T>(
  fn: () => Promise<T | undefined | false>,
  { timeoutMs = 90_000, intervalMs = 2_000, label = 'condition' } = {},
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let last: unknown;
  while (Date.now() < deadline) {
    try {
      const v = await fn();
      if (v) return v as T;
    } catch (err) {
      last = err;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`timed out waiting for ${label}${last ? `: ${String(last)}` : ''}`);
}

/** Nudge the completed-download → import machinery (event-triggered, but this
 *  makes the hermetic run deterministic without waiting on the ~60s poll). */
export async function nudgeImport(api: APIRequestContext): Promise<void> {
  await api.post('/api/v1/command', { data: { name: 'track-downloads' } });
  await api.post('/api/v1/command', { data: { name: 'process-imports' } });
}
