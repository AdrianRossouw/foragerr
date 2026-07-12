import { test, expect, request as pwRequest } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASSWORD, EMPTY_STORAGE_STATE, newBareContext } from './helpers';

/**
 * Mandatory-auth negative paths across every surface (m8-auth-core, task 5.7).
 * This is the (c) leg of the three-way FRG-AUTH-010 proof — end-to-end refusals
 * on each surface against the REAL container — complementing the backend's
 * construction proof (root dependency) and its exhaustive route-inventory test.
 * Also pins the CSRF/Origin stance (FRG-SEC-005), the OPDS Basic realm, generic
 * login failure (FRG-AUTH-002), server-side logout invalidation (FRG-AUTH-004),
 * and that the authenticated WebSocket handshake actually succeeds when a real
 * logged-in browser connects (proving the socket perimeter admits the good path,
 * not just refuses the bad one).
 *
 * Named `z-auth-*` so it runs AFTER the spine/library/daily scenarios but
 * BEFORE the container-mutating `zz-*` specs (restart / keyless recreate) that
 * reassign the ephemeral host port — it reads the app on the stable
 * FORAGERR_BASE_URL. It shares no state with the serial spine: every browser
 * check uses a FRESH, cookie-less context (so it is genuinely "logged out"),
 * and the one authenticated check uses the project's saved session — neither
 * disturbs the growing library the other specs rely on.
 */

const BASE_URL = process.env.FORAGERR_BASE_URL ?? 'http://127.0.0.1:8789';

test.describe('mandatory-auth negative paths', () => {
  test.skip(
    !process.env.FORAGERR_E2E_RUN,
    'no compose run dir provided (run via e2e/run.sh)',
  );

  test('FRG-AUTH-010 FRG-PROC-010: a bare API request (no credential) is refused 401', async () => {
    const bare = await newBareContext(BASE_URL);
    // A GET with neither session cookie nor X-Api-Key is default-denied.
    const res = await bare.get('/api/v1/series?page=1&pageSize=1');
    expect(res.status(), 'bare API GET is refused').toBe(401);
    // The uniform 4xx body shape ({"message": ...}) — never FastAPI's raw detail.
    expect((await res.json()).message).toBeTruthy();

    // The OpenAPI schema is not publicly served: the interactive docs are gone
    // and the schema route is disabled outright (404), so a bare caller cannot
    // read the API surface either way — never a 200.
    expect(
      [401, 404],
      'openapi schema is not publicly served',
    ).toContain((await bare.get('/openapi.json')).status());
    await bare.dispose();
  });

  test('FRG-AUTH-010 FRG-PROC-010: OPDS answers a bare request with a Basic realm challenge, then serves with Basic creds', async () => {
    const bare = await newBareContext(BASE_URL);

    // Bare OPDS: 401 WITH the Basic challenge naming the OPDS realm (so an iPad
    // reader is prompted for the reader password rather than silently failing).
    const challenged = await bare.get('/opds');
    expect(challenged.status(), 'bare OPDS is refused').toBe(401);
    expect(
      challenged.headers()['www-authenticate'],
      'the OPDS Basic realm challenge',
    ).toContain('Basic realm="foragerr-opds"');

    // With correct Basic creds the feed is served. The OPDS password equals the
    // admin password at seed (FORAGERR_OPDS_PASSWORD unset); the username binds
    // to the admin user — readers must be configured with both.
    const basic = Buffer.from(`${ADMIN_USER}:${ADMIN_PASSWORD}`).toString('base64');
    const served = await bare.get('/opds', {
      headers: { authorization: `Basic ${basic}` },
    });
    expect(served.status(), 'OPDS served with Basic creds').toBe(200);
    expect(served.headers()['content-type']).toContain('application/atom+xml');

    // A wrong Basic password stays refused (the realm is not a rubber stamp).
    const wrong = Buffer.from(`${ADMIN_USER}:not-the-password`).toString('base64');
    const denied = await bare.get('/opds', { headers: { authorization: `Basic ${wrong}` } });
    expect(denied.status(), 'wrong Basic password is refused').toBe(401);
    await bare.dispose();
  });

  test('FRG-SEC-005 FRG-PROC-010: a cookie-authed unsafe method with a foreign Origin is refused 403, and the X-Api-Key surface is immune', async () => {
    // Establish a real cookie session in an isolated context (the login route is
    // the one perimeter-exempt door). Empty storageState so the ONLY cookie is
    // the one this login sets — otherwise the context would inherit the shared
    // project session and login's fixation defense would delete it.
    const ctx = await pwRequest.newContext({
      baseURL: BASE_URL,
      ignoreHTTPSErrors: true,
      storageState: EMPTY_STORAGE_STATE,
    });
    const loggedIn = await ctx.post('/api/v1/auth/login', {
      data: { username: ADMIN_USER, password: ADMIN_PASSWORD, remember: false },
    });
    expect(loggedIn.status(), 'login establishes a session').toBe(200);

    // A cookie-authed POST carrying a FOREIGN Origin is a classic CSRF shape:
    // refused 403 before the handler (FRG-SEC-005), even though the cookie is
    // valid. (rootfolder is a convenient state-changing endpoint; the request
    // never reaches its handler.)
    const forged = await ctx.post('/api/v1/rootfolder', {
      headers: { origin: 'https://evil.example.com' },
      data: { path: '/library' },
    });
    expect(forged.status(), 'foreign-Origin cookie POST is CSRF-blocked').toBe(403);

    // The SAME cookie POST with the app's own Origin passes the CSRF gate (it
    // then fails only on app logic — the root is already registered — which is a
    // 4xx that is NOT the 403 CSRF refusal; the point is the perimeter admits it).
    const sameOrigin = await ctx.post('/api/v1/rootfolder', {
      headers: { origin: BASE_URL },
      data: { path: '/library' },
    });
    expect(
      sameOrigin.status(),
      'same-Origin cookie POST clears the CSRF gate (reaches the handler)',
    ).not.toBe(403);
    await ctx.dispose();

    // The X-Api-Key surface is CSRF-immune by construction: a foreign Origin on
    // an unsafe method does NOT trigger the 403 (a browser cannot attach the
    // header cross-site, so the check is skipped).
    const keyed = await pwRequest.newContext({
      baseURL: BASE_URL,
      ignoreHTTPSErrors: true,
      storageState: EMPTY_STORAGE_STATE,
      extraHTTPHeaders: { 'X-Api-Key': process.env.E2E_API_KEY ?? '' },
    });
    const keyedPost = await keyed.post('/api/v1/rootfolder', {
      headers: { origin: 'https://evil.example.com' },
      data: { path: '/library' },
    });
    expect(
      keyedPost.status(),
      'X-Api-Key POST is immune to the CSRF Origin check',
    ).not.toBe(403);
    await keyed.dispose();
  });

  test('FRG-AUTH-010 FRG-PROC-010: a logged-out UI visit to a protected route lands on the login screen', async ({ browser }) => {
    const guest = await browser.newContext({
      baseURL: BASE_URL,
      ignoreHTTPSErrors: true,
      storageState: { cookies: [], origins: [] },
    });
    const page = await guest.newPage();
    await page.goto('/wanted');
    // AuthGate redirects to /login, preserving the intended path as ?return=.
    await page.waitForURL(/\/login\?return=/, { timeout: 30_000 });
    await expect(page.getByRole('button', { name: /Sign in/ })).toBeVisible();
    await guest.close();
  });

  test('FRG-AUTH-002 FRG-PROC-010: a wrong password yields a generic error and establishes no session', async ({ browser }) => {
    const guest = await browser.newContext({
      baseURL: BASE_URL,
      ignoreHTTPSErrors: true,
      storageState: { cookies: [], origins: [] },
    });
    const page = await guest.newPage();
    await page.goto('/login');
    await page.getByLabel('Username').fill(ADMIN_USER);
    await page.getByLabel('Password').fill('definitely-the-wrong-password');
    await page.getByRole('button', { name: /Sign in/ }).click();

    // The generic failure message (no user-enumeration: bad-user and
    // bad-password are indistinguishable).
    await expect(page.getByRole('alert')).toHaveText('Invalid username or password.');
    // And genuinely no session: /auth/me over the guest context's own (empty)
    // cookie jar is still refused.
    expect((await guest.request.get('/api/v1/auth/me')).status()).toBe(401);
    await guest.close();
  });

  test('FRG-AUTH-010 FRG-PROC-010: logging in returns the operator to the intended (return) path', async ({ browser }) => {
    const guest = await browser.newContext({
      baseURL: BASE_URL,
      ignoreHTTPSErrors: true,
      storageState: { cookies: [], origins: [] },
    });
    const page = await guest.newPage();
    await page.goto('/login?return=%2Fwanted');
    await page.getByLabel('Username').fill(ADMIN_USER);
    await page.getByLabel('Password').fill(ADMIN_PASSWORD);
    await page.getByRole('button', { name: /Sign in/ }).click();

    // Lands on the requested path, not a generic home bounce.
    await page.waitForURL(/\/wanted$/, { timeout: 30_000 });
    await expect(page.getByTestId('sidebar-status')).toBeVisible();
    await guest.close();
  });

  test('FRG-AUTH-004 FRG-PROC-010: after logout the old session token is dead — replaying it yields 401', async () => {
    // Own isolated session so this never touches the shared project session
    // (empty storageState: no inherited cookie for login's fixation defense to
    // invalidate).
    const ctx = await pwRequest.newContext({
      baseURL: BASE_URL,
      ignoreHTTPSErrors: true,
      storageState: EMPTY_STORAGE_STATE,
    });
    const loggedIn = await ctx.post('/api/v1/auth/login', {
      data: { username: ADMIN_USER, password: ADMIN_PASSWORD, remember: false },
    });
    expect(loggedIn.status()).toBe(200);
    expect((await ctx.get('/api/v1/auth/me')).status(), 'session is live before logout').toBe(200);

    // Capture the raw token so we can replay it AFTER logout — proving the row
    // is deleted server-side, not merely that the cookie was cleared locally.
    const state = await ctx.storageState();
    const token = state.cookies.find((c) => c.name === 'foragerr_session')?.value;
    expect(token, 'the session cookie was set').toBeTruthy();

    // Logout is a cookie-authed unsafe POST, so it carries the app's own Origin.
    const out = await ctx.post('/api/v1/auth/logout', { headers: { origin: BASE_URL } });
    expect(out.status(), 'logout succeeds').toBe(204);
    await ctx.dispose();

    // Replay the exact old token against a fresh context: the deleted session
    // no longer authenticates — a hard 401.
    const replay = await pwRequest.newContext({
      baseURL: BASE_URL,
      ignoreHTTPSErrors: true,
      storageState: EMPTY_STORAGE_STATE,
      extraHTTPHeaders: { cookie: `foragerr_session=${token}` },
    });
    expect(
      (await replay.get('/api/v1/auth/me')).status(),
      'the logged-out token is dead',
    ).toBe(401);
    await replay.dispose();
  });

  test('FRG-AUTH-010 FRG-SEC-005 FRG-PROC-010: a logged-in browser establishes the authenticated WebSocket (real-time connection goes live)', async ({ page }) => {
    // This test uses the project's SAVED session (storageState). The SPA opens
    // /api/v1/ws on load; the handshake must pass the same perimeter (cookie +
    // Origin allowlist) BEFORE upgrade. The sidebar footer's connection dot
    // flips to data-status="connected" only once that socket is actually open —
    // so this asserts the GOOD path through the socket perimeter end-to-end.
    await page.goto('/');
    const conn = page.getByTestId('connection-status');
    await expect(conn).toBeVisible();
    await expect(conn).toHaveAttribute('data-status', 'connected', { timeout: 30_000 });
  });
});
