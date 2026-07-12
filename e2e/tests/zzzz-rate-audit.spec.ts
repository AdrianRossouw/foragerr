import { test, expect, request as pwRequest } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  ADMIN_USER,
  EMPTY_STORAGE_STATE,
  currentAdminPassword,
  currentOpdsPassword,
  newApiContext,
} from './helpers';

/**
 * Failed-auth rate limiting + audit trail, end-to-end (m8-rate-audit, task 4.1,
 * FRG-AUTH-009): a scripted bad-login burst trips 429 + `Retry-After` before any
 * password hashing, the escalation is visible as a structured `foragerr.auth`
 * audit trail with no credential material leaked into it, and — after the
 * `Retry-After` deadline passes — correct credentials succeed normally (no hard
 * lockout), which also resets the counter this file drove up.
 *
 * Named `zzzz-*` (sorts after `zzz-credential-lifecycle.spec.ts`) so it runs
 * ABSOLUTELY LAST. This is load-bearing, not stylistic: every request in this
 * whole suite originates from ONE client IP (the compose network's egress from
 * the Playwright/API-request process), and FRG-AUTH-009 keys its enforcing
 * counters per (client IP, surface) — so a login-failure burst here would
 * throttle the `login` surface for every later test if anything ran after it.
 * The login burst test restores clean state itself: a SUCCESSFUL
 * authentication resets the counter for its (IP, surface) key (the design's
 * reset-on-success rule), so it recovers via a correct login after its
 * deadline. The OPDS Basic burst (the final test) deliberately does NOT
 * recover: a throttled key refuses even correct credentials until the
 * deadline passes (the limiter runs BEFORE verification, so success-reset is
 * unreachable while throttled — asserted below), and waiting out a second
 * 30s deadline buys nothing since nothing runs after this file and run.sh
 * tears the stack down with `compose down`.
 *
 * zzz-credential-lifecycle.spec.ts runs immediately before this file and its
 * very last test ends with a successful login, which resets the `login`
 * surface's enforcing counter to empty for this client IP — so this file's
 * burst starts from a clean slate for enforcement purposes. The *global*
 * per-surface observability counter (never reset by success, by design) may
 * already carry a stray failure or two from earlier specs (e.g.
 * z-auth-negative.spec.ts's one wrong-password check); that only means the
 * rising-edge `auth.backoff_triggered` event may fire a request or two earlier
 * than the enforcing 429 — this file asserts the event's presence, not which
 * exact attempt produced it.
 *
 * Like the zz- and zzz- specs, this file never trusts `FORAGERR_BASE_URL`
 * (zz-unconfigured recreated the app container, reassigning the ephemeral host
 * port) — it re-discovers the live port mapping first.
 *
 * zzz-credential-lifecycle.spec.ts also rotates the admin AND OPDS passwords
 * away from the bootstrap `ADMIN_PASSWORD` constant, so every "correct
 * credential" check below reads the LIVE value via
 * `currentAdminPassword()`/`currentOpdsPassword()` (helpers.ts) rather than
 * the bootstrap constant — see those functions' doc comment.
 */

const COMPOSE_FILE = fileURLToPath(new URL('../compose.yaml', import.meta.url));
const COMPOSE = ['compose', '-f', COMPOSE_FILE, '-p', 'foragerr-e2e'];

// A distinctive, never-correct password used only by this file's burst tests —
// distinctive so the credential-leak negative check (test 2) can search the
// captured log text for this exact string with no risk of coincidentally
// matching some other fixture value.
const WRONG_PASSWORD = 'e2e-ratelimit-wrong-9f2c8b41';

test.describe.serial('failed-auth rate limiting + audit (FRG-AUTH-009)', () => {
  test.skip(
    !process.env.FORAGERR_E2E_RUN,
    'no compose run dir provided (run via e2e/run.sh)',
  );

  let base: string;
  // Populated by test 1, consumed by test 2 (log content) and test 3
  // (recovery timing) — mirrors zzz-credential-lifecycle's cross-test state
  // threading via closures in the same describe.serial block.
  let retryAfterSeconds = 0;
  let throttledAt = 0;

  test.beforeAll(() => {
    const mapping = execFileSync('docker', [...COMPOSE, 'port', 'foragerr', '8789'], {
      env: { ...process.env, E2E_CV_API_KEY: '' },
    }).toString();
    const port = mapping.trim().split('\n')[0].trim().split(':').pop();
    base = `http://127.0.0.1:${port}`;
  });

  test('FRG-AUTH-009: a bad-login burst is throttled with 429 and a Retry-After deadline', async () => {
    const ctx = await pwRequest.newContext({
      baseURL: base,
      ignoreHTTPSErrors: true,
      storageState: EMPTY_STORAGE_STATE,
    });

    // Drive wrong-password attempts until the surface trips. The FIRST time a
    // key is throttled the deadline is always the un-escalated base (30s,
    // excess=0) regardless of how many prior failures were already in the
    // window — so stopping at the first 429 keeps the wait in test 3 short
    // and bounded, however many stray failures preceded this burst. Bounded
    // at 8 attempts: the enforcing counter resets to empty after
    // zzz-credential-lifecycle's final successful login, so 5 failures
    // (the FAILURE_THRESHOLD) should trip the 6th — 8 leaves headroom without
    // risking a second backoff escalation (which would double the wait).
    const MAX_ATTEMPTS = 8;
    let failures = 0;
    let throttledResponse: Awaited<ReturnType<typeof ctx.post>> | null = null;
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
      const res = await ctx.post('/api/v1/auth/login', {
        data: { username: ADMIN_USER, password: WRONG_PASSWORD, remember: false },
      });
      if (res.status() === 429) {
        throttledResponse = res;
        throttledAt = Date.now();
        break;
      }
      expect(res.status(), `attempt ${attempt} is a generic auth failure, not throttled yet`).toBe(401);
      failures += 1;
    }

    expect(throttledResponse, 'the burst eventually trips the 429 throttle').not.toBeNull();
    expect(failures, 'at least the threshold worth of 401s preceded the throttle').toBeGreaterThanOrEqual(5);

    const retryAfter = throttledResponse!.headers()['retry-after'];
    expect(retryAfter, 'the 429 carries a Retry-After header').toBeTruthy();
    retryAfterSeconds = Number(retryAfter);
    expect(Number.isFinite(retryAfterSeconds), 'Retry-After is an integer number of seconds').toBe(true);
    expect(retryAfterSeconds, 'Retry-After is at least 1 second').toBeGreaterThanOrEqual(1);
    // The un-escalated base deadline (30s) plus generous slack for the
    // request/response round trip — proves this is the FIRST-trip deadline,
    // not an already-escalated one from a prior stray burst.
    expect(retryAfterSeconds, 'the first trip is the un-escalated base deadline, not an escalated one').toBeLessThanOrEqual(35);

    const body = await throttledResponse!.json();
    expect(body.message, 'the 429 body is the shared uniform shape').toBeTruthy();

    await ctx.dispose();
  });

  test('FRG-AUTH-009: the audit trail records the failures and the backoff escalation, with no credential material', async () => {
    const api = await newApiContext(base);
    // The API-key surface is independent of the login-surface throttle this
    // burst just tripped, so this authenticated read is unaffected by it.
    const res = await api.get('/api/v1/log?logger=foragerr.auth&pageSize=200');
    expect(res.status(), 'authenticated log read succeeds').toBe(200);
    const page = await res.json();
    const messages: string[] = (page.records as Array<{ message: string }>).map((r) => r.message);
    const fullText = messages.join('\n');

    const failureLines = messages.filter((m) => m.startsWith('auth.login.failure '));
    expect(failureLines.length, 'the burst\'s login failures are audited').toBeGreaterThanOrEqual(5);
    for (const line of failureLines.slice(0, 5)) {
      expect(line, 'each failure line names the login surface and this IP').toContain('surface=login');
    }

    const backoffLines = messages.filter((m) => m.startsWith('auth.backoff_triggered '));
    expect(backoffLines.length, 'the escalation fires an auth.backoff_triggered event').toBeGreaterThanOrEqual(1);
    expect(
      backoffLines.some((l) => l.includes('surface=login')),
      'at least one backoff event names the login surface',
    ).toBe(true);

    // Credential-leak negative check: the wrong password used to drive the
    // burst never appears anywhere in the captured audit text.
    expect(fullText, 'the submitted wrong password never reaches the log').not.toContain(WRONG_PASSWORD);

    await api.dispose();
  });

  test('FRG-AUTH-009: no hard lockout — after the Retry-After deadline, correct credentials succeed and reset the counter', async () => {
    // Wait out the remaining deadline measured from the exact moment the 429
    // was observed (not from test start — test 2's log read already consumed
    // some of it), plus a small buffer so a scheduling jitter never lands us
    // a request early.
    const elapsedMs = Date.now() - throttledAt;
    const remainingMs = retryAfterSeconds * 1000 - elapsedMs + 2_000;
    if (remainingMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, remainingMs));
    }

    const ctx = await pwRequest.newContext({
      baseURL: base,
      ignoreHTTPSErrors: true,
      storageState: EMPTY_STORAGE_STATE,
    });
    const password = currentAdminPassword();
    const res = await ctx.post('/api/v1/auth/login', {
      data: { username: ADMIN_USER, password, remember: false },
    });
    expect(res.status(), 'correct credentials succeed after the deadline — no lockout').toBe(200);

    // Prove the reset-on-success actually happened (not just that this one
    // request got through): an immediate follow-up login also succeeds with
    // no throttle in the way, restoring the clean state this file promises.
    const again = await ctx.post('/api/v1/auth/login', {
      data: { username: ADMIN_USER, password, remember: false },
    });
    expect(again.status(), 'the counter is reset — an immediate follow-up login is not throttled').toBe(200);

    await ctx.dispose();
  });

  test('FRG-AUTH-009: OPDS Basic is throttled and isolated from the login surface (key isolation)', async () => {
    // Cheap: OPDS Basic shares the same limiter machinery on its own `basic`
    // surface key — no long deadline wait required, so this rides along in
    // the same file rather than deferring entirely to the backend
    // unit/enforcement tests.
    const ctx = await pwRequest.newContext({
      baseURL: base,
      ignoreHTTPSErrors: true,
      storageState: EMPTY_STORAGE_STATE,
    });
    const wrongBasic = Buffer.from(`${ADMIN_USER}:${WRONG_PASSWORD}`).toString('base64');

    const MAX_ATTEMPTS = 8;
    let failures = 0;
    let throttled: Awaited<ReturnType<typeof ctx.get>> | null = null;
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
      const res = await ctx.get('/opds', { headers: { authorization: `Basic ${wrongBasic}` } });
      if (res.status() === 429) {
        throttled = res;
        break;
      }
      expect(res.status(), `OPDS attempt ${attempt} is a plain refusal, not throttled yet`).toBe(401);
      failures += 1;
    }
    expect(throttled, 'the OPDS Basic burst trips the 429 throttle').not.toBeNull();
    expect(failures, 'at least the threshold worth of 401s preceded the throttle').toBeGreaterThanOrEqual(5);
    expect(throttled!.headers()['retry-after'], 'the OPDS 429 carries Retry-After too').toBeTruthy();

    // A throttled key refuses even CORRECT credentials until the deadline
    // passes — the limiter runs BEFORE verification, so success-reset is
    // unreachable while throttled. Asserted on this cookie-less context: the
    // login-isolation check below must come AFTER this (its successful login
    // would set a session cookie on its context, and a cookie'd request
    // authenticates at the perimeter's cookie step without ever reaching the
    // Basic branch — masking the throttle entirely).
    const correctBasic = Buffer.from(`${ADMIN_USER}:${currentOpdsPassword()}`).toString('base64');
    const correctDuringDeadline = await ctx.get('/opds', {
      headers: { authorization: `Basic ${correctBasic}` },
    });
    expect(
      correctDuringDeadline.status(),
      'correct Basic creds are also refused during the deadline — the limiter precedes verification',
    ).toBe(429);

    // The login surface (proven throttled-then-recovered above, in a
    // completely separate part of this same test file) is a DIFFERENT
    // (IP, surface) key — the operator's login is never collateral damage
    // from a misbehaving reader hammering OPDS Basic on the same address.
    const loginStillOpen = await ctx.post('/api/v1/auth/login', {
      data: { username: ADMIN_USER, password: currentAdminPassword(), remember: false },
    });
    expect(
      loginStillOpen.status(),
      'the login surface is untouched by the OPDS Basic throttle on the same IP',
    ).toBe(200);

    // No basic-surface restore: nothing runs after this file and run.sh tears
    // the stack down — see the header comment.
    await ctx.dispose();
  });
});
