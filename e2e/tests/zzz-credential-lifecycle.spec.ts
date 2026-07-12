import { test, expect, request as pwRequest, type APIRequestContext } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { ADMIN_USER, ADMIN_PASSWORD, EMPTY_STORAGE_STATE } from './helpers';

/**
 * Credential-lifecycle end-to-end (m8-keys-opds, tasks 5.1-5.4): password
 * change with acting-session preservation (FRG-AUTH-004), API-key rotation
 * with immediate old-key invalidation (FRG-AUTH-007, key-survives-password
 * cross-check FRG-AUTH-006), independent OPDS password change with immediate
 * verify-cache invalidation (FRG-AUTH-005), and logout-all (FRG-AUTH-004) —
 * all against the REAL container over the network, per the UAT
 * negative-paths rule (every re-auth miss is asserted generic).
 *
 * Named `zzz-*` so it runs near the very end: it burns the credentials every
 * earlier spec depends on — rotating the key kills the bootstrap `E2E_API_KEY`,
 * and the admin password change invalidates the saved storage-state session.
 * No restore is attempted here (run.sh tears down with `compose down`; a retry
 * re-runs against whatever credentials the previous attempt left, so every
 * step derives its inputs from the LIVE state it creates rather than assuming
 * the bootstrap values — see `currentAdminPw`).
 *
 * One file now runs after this one — `zzzz-rate-audit.spec.ts` (FRG-AUTH-009) —
 * because its login-failure burst would throttle the `login` surface for every
 * other spec if it ran anywhere else (every request in this suite shares one
 * client IP). That file cannot use the bootstrap `ADMIN_PASSWORD`/OPDS-password
 * constants for "correct credential" checks once this file has rotated them, so
 * this file threads the LIVE final values through `process.env` at the point
 * each rotation is confirmed (`E2E_CURRENT_ADMIN_PASSWORD`,
 * `E2E_CURRENT_OPDS_PASSWORD`) — same pattern as the existing `E2E_API_KEY`
 * threading for key rotation, just two more env vars.
 *
 * zz-unconfigured recreated the app container (new ephemeral host port), so
 * like the zz specs this one re-discovers the mapping first and never trusts
 * FORAGERR_BASE_URL.
 */

const COMPOSE_FILE = fileURLToPath(new URL('../compose.yaml', import.meta.url));
const COMPOSE = ['compose', '-f', COMPOSE_FILE, '-p', 'foragerr-e2e'];

/** Cookie-jar context logged in as the operator; unsafe methods thread Origin
 * (FRG-SEC-005 — a cookie-authed POST without our own Origin is refused). */
async function login(
  base: string,
  password: string,
  remember = false,
): Promise<APIRequestContext> {
  const ctx = await pwRequest.newContext({
    baseURL: base,
    ignoreHTTPSErrors: true,
    storageState: EMPTY_STORAGE_STATE,
    extraHTTPHeaders: { Origin: base },
  });
  const res = await ctx.post('/api/v1/auth/login', {
    data: { username: ADMIN_USER, password, remember },
  });
  expect(res.ok(), `login as ${ADMIN_USER} succeeds`).toBe(true);
  return ctx;
}

async function opdsStatus(base: string, password: string): Promise<number> {
  const basic = Buffer.from(`${ADMIN_USER}:${password}`).toString('base64');
  const ctx = await pwRequest.newContext({
    baseURL: base,
    ignoreHTTPSErrors: true,
    storageState: EMPTY_STORAGE_STATE,
    extraHTTPHeaders: { Authorization: `Basic ${basic}` },
  });
  try {
    return (await ctx.get('/opds')).status();
  } finally {
    await ctx.dispose();
  }
}

async function apiKeyStatus(base: string, key: string): Promise<number> {
  const ctx = await pwRequest.newContext({
    baseURL: base,
    ignoreHTTPSErrors: true,
    storageState: EMPTY_STORAGE_STATE,
    extraHTTPHeaders: { 'X-Api-Key': key },
  });
  try {
    return (await ctx.get('/api/v1/series?page=1&pageSize=1')).status();
  } finally {
    await ctx.dispose();
  }
}

test.describe.serial('credential lifecycle', () => {
  test.skip(
    !process.env.FORAGERR_E2E_RUN,
    'no compose run dir provided (run via e2e/run.sh)',
  );

  let base: string;
  // The password steps run AFTER the OPDS/key steps and mutate the admin
  // credential; every step reads these instead of the bootstrap constants so
  // a retried run (which may inherit a half-mutated container) still orders
  // its assertions against what it itself established.
  let currentAdminPw = ADMIN_PASSWORD;
  const NEW_OPDS_PW = 'e2e-opds-rotated-5f81c2';
  const NEW_ADMIN_PW = 'e2e-admin-rotated-7d24aa';

  test.beforeAll(() => {
    // zz-unconfigured's recreate reassigned the ephemeral port — re-discover.
    const mapping = execFileSync('docker', [...COMPOSE, 'port', 'foragerr', '8789'], {
      env: { ...process.env, E2E_CV_API_KEY: '' },
    }).toString();
    const port = mapping.trim().split('\n')[0].trim().split(':').pop();
    base = `http://127.0.0.1:${port}`;
  });

  test('FRG-AUTH-005: OPDS password changes independently and old Basic creds die instantly', async () => {
    const acting = await login(base, currentAdminPw);

    // Seeded state: OPDS password equals the admin password (no env override
    // in compose.yaml), and the verify-cache is about to hold a POSITIVE
    // entry for it — the strongest version of the invalidation assertion.
    expect(await opdsStatus(base, currentAdminPw), 'seeded OPDS creds serve').toBe(200);

    const changed = await acting.post('/api/v1/auth/opds-password', {
      data: { current_password: currentAdminPw, new_password: NEW_OPDS_PW },
    });
    expect(changed.status(), 'OPDS password change accepted').toBe(204);

    // Immediately — no TTL grace: the cache was cleared on the write.
    expect(await opdsStatus(base, currentAdminPw), 'old OPDS creds are dead').toBe(401);
    expect(await opdsStatus(base, NEW_OPDS_PW), 'new OPDS creds serve').toBe(200);
    // Threaded for zzzz-rate-audit.spec.ts (the ONE file that now runs after
    // this one): the OPDS password no longer matches ADMIN_PASSWORD past this
    // point, so any later spec needing a CORRECT OPDS credential must read the
    // live value rather than the bootstrap constant. Mirrors the existing
    // E2E_API_KEY threading below for key rotation.
    process.env.E2E_CURRENT_OPDS_PASSWORD = NEW_OPDS_PW;

    // Independence: the WEB session and admin password are untouched.
    expect((await acting.get('/api/v1/auth/me')).status(), 'web session unaffected').toBe(200);

    // Re-auth miss is generic: wrong admin password, identical failure shape.
    const denied = await acting.post('/api/v1/auth/opds-password', {
      data: { current_password: 'wrong-password', new_password: 'whatever-x1' },
    });
    expect(denied.status(), 'wrong re-auth password refused').toBe(403);
    expect(await opdsStatus(base, NEW_OPDS_PW), 'OPDS password unchanged by refusal').toBe(200);

    await acting.dispose();
  });

  test('FRG-AUTH-007 FRG-AUTH-006: key rotation kills the old key immediately; re-auth required', async () => {
    const oldKey = process.env.E2E_API_KEY!;
    const acting = await login(base, currentAdminPw);

    expect(await apiKeyStatus(base, oldKey), 'bootstrap key works before rotation').toBe(200);

    // Wrong re-auth: refused generically, key unchanged.
    const denied = await acting.post('/api/v1/auth/api-key/rotate', {
      data: { current_password: 'wrong-password' },
    });
    expect(denied.status(), 'rotation without re-auth refused').toBe(403);
    expect(await apiKeyStatus(base, oldKey), 'key unchanged by refused rotation').toBe(200);

    const rotated = await acting.post('/api/v1/auth/api-key/rotate', {
      data: { current_password: currentAdminPw },
    });
    expect(rotated.status(), 'rotation accepted').toBe(200);
    const newKey: string = (await rotated.json()).api_key;
    expect(newKey, 'rotation response carries the raw key once').toBeTruthy();
    expect(newKey).not.toBe(oldKey);

    expect(await apiKeyStatus(base, oldKey), 'old key 401s from the next request').toBe(401);
    expect(await apiKeyStatus(base, newKey), 'new key serves').toBe(200);
    process.env.E2E_API_KEY = newKey; // later steps' cross-checks use the live key

    await acting.dispose();
  });

  test('FRG-AUTH-004: password change preserves the acting session and kills every other', async () => {
    const acting = await login(base, currentAdminPw);
    const other = await login(base, currentAdminPw, /* remember */ true);

    const changed = await acting.post('/api/v1/auth/password', {
      data: { current_password: currentAdminPw, new_password: NEW_ADMIN_PW },
    });
    expect(changed.status(), 'password change accepted').toBe(204);
    const oldAdminPw = currentAdminPw;
    currentAdminPw = NEW_ADMIN_PW;
    // Threaded for zzzz-rate-audit.spec.ts, same reasoning as
    // E2E_CURRENT_OPDS_PASSWORD above: the admin/login password no longer
    // matches ADMIN_PASSWORD past this point.
    process.env.E2E_CURRENT_ADMIN_PASSWORD = NEW_ADMIN_PW;

    // Acting session sails on; the other (remember-me!) session is dead.
    expect((await acting.get('/api/v1/auth/me')).status(), 'acting session preserved').toBe(200);
    expect((await other.get('/api/v1/auth/me')).status(), 'other session invalidated').toBe(401);

    // Old password no longer logs in — and the failure is the same generic
    // shape as any bad credential (no oracle that it USED to be right).
    const bare = await pwRequest.newContext({
      baseURL: base,
      ignoreHTTPSErrors: true,
      storageState: EMPTY_STORAGE_STATE,
    });
    const stale = await bare.post('/api/v1/auth/login', {
      data: { username: ADMIN_USER, password: oldAdminPw },
    });
    expect(stale.status(), 'old password refused at login').toBe(401);
    await bare.dispose();

    // Cross-surface independence: the API key (FRG-AUTH-006) and the OPDS
    // password (FRG-AUTH-005) both survive the web password change.
    expect(await apiKeyStatus(base, process.env.E2E_API_KEY!), 'API key survives').toBe(200);
    expect(await opdsStatus(base, NEW_OPDS_PW), 'OPDS password survives').toBe(200);

    await acting.dispose();
    await other.dispose();
  });

  test('FRG-AUTH-004: logout-all destroys every session including the acting one', async () => {
    const acting = await login(base, currentAdminPw);
    const second = await login(base, currentAdminPw, /* remember */ true);

    const res = await acting.post('/api/v1/auth/logout-all');
    expect(res.status(), 'logout-all accepted').toBe(204);

    expect((await acting.get('/api/v1/auth/me')).status(), 'acting session destroyed').toBe(401);
    expect((await second.get('/api/v1/auth/me')).status(), 'second session destroyed').toBe(401);

    // Not a lockout: a fresh login with the current password still works.
    const back = await login(base, currentAdminPw);
    expect((await back.get('/api/v1/auth/me')).status(), 'fresh login works after logout-all').toBe(200);

    await acting.dispose();
    await second.dispose();
    await back.dispose();
  });
});
