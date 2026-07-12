import { test as setup, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { ADMIN_USER, ADMIN_PASSWORD, STORAGE_STATE } from './helpers';

/**
 * Authenticated-session setup project (m8-auth-core, tasks 5.7 / FRG-AUTH-010).
 *
 * The whole app now enforces mandatory login, so every browser-driven scenario
 * must arrive already authenticated or it would be bounced to /login. This
 * project runs ONCE before the rest of the suite (a `dependencies` edge in
 * playwright.config.ts), drives the REAL login form exactly as an operator
 * would, and saves the resulting session to `STORAGE_STATE`. Every other
 * project loads that `storageState`, so the existing spine/library/daily/etc.
 * scenarios stay green with no per-spec login code — one seam, matching the
 * backend's one-dependency perimeter.
 *
 * The cookie is host-only (no Domain attribute), so it is replayed to
 * 127.0.0.1 on ANY port — that is what keeps the authenticated `page` working
 * for the zz-* specs after a restart/recreate reassigns the ephemeral host
 * port. The session row lives in the DB on the persisted /config volume, so it
 * also survives those container restarts.
 */
setup('authenticate: log in through the UI and save the session', async ({ page }) => {
  mkdirSync(path.dirname(STORAGE_STATE), { recursive: true });

  // A cookie-less visit to a protected route bounces to /login (AuthGate);
  // going straight to /login is the same door without the redirect hop.
  await page.goto('/login');
  await expect(page.getByRole('button', { name: /Sign in/ })).toBeVisible();

  await page.getByLabel('Username').fill(ADMIN_USER);
  await page.getByLabel('Password').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /Sign in/ }).click();

  // On success AuthGate/LoginScreen navigate off /login to the app shell.
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), {
    timeout: 30_000,
  });
  // The app shell is really mounted (not a login-error flash): its footer
  // status row only renders inside the authenticated tree.
  await expect(page.getByTestId('sidebar-status')).toBeVisible();

  await page.context().storageState({ path: STORAGE_STATE });
});
