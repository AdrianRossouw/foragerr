import { test, expect } from '@playwright/test';

/**
 * Sources screen — first-run + connect negative paths (FRG-UI-029, FRG-PROC-010
 * UAT negative-path policy). Drives the REAL app container; no source is
 * connected, so this exercises the unconfigured first-run render and the connect
 * endpoint's failure path exactly as an operator would hit them.
 *
 * NOTE (reported gap): a connect-SUCCESS / review / expired-state journey cannot
 * run in the hermetic stack because the Humble API base URL is hardcoded
 * (`sources/humble.py: HUMBLE_API_BASE`) with no override to point at a fixture —
 * unlike ComicVine's `FORAGERR_COMICVINE_BASE_URL`. So the positive flow and the
 * expired state are covered by the vitest component suite (FRG-UI-029) instead;
 * add a `FORAGERR_HUMBLE_BASE_URL` override + mockhub order endpoints to lift
 * them into e2e.
 */

test.describe('FRG-UI-029 Sources', () => {
  test.skip(
    !process.env.FORAGERR_E2E_RUN,
    'no compose run dir provided (run via e2e/run.sh)',
  );

  test('FRG-UI-029: an unconfigured Sources screen shows the Humble connect card and DevTools helper', async ({
    page,
  }) => {
    await page.goto('/sources');

    // The store rail + connect card render for a source-less first run.
    await expect(page.getByRole('button', { name: /Humble Bundle/ })).toBeVisible();
    const card = page.getByTestId('connect-card');
    await expect(card).toBeVisible();

    // The cookie field is masked (type=password) and Connect is disabled until
    // a plausible-length value is pasted.
    const input = page.getByTestId('cookie-input');
    await expect(input).toHaveAttribute('type', 'password');
    await expect(page.getByTestId('connect-button')).toBeDisabled();

    // The helper reveals the extension "coming soon" chip and the cookie name.
    await page.getByTestId('helper-toggle').click();
    const helper = page.getByTestId('cookie-helper');
    await expect(helper.getByText('Coming soon')).toBeVisible();
    await expect(helper.getByText('_simpleauth_sess')).toBeVisible();

    // Typing past the threshold enables Connect.
    await input.fill('_simpleauth_sess=this-is-a-long-enough-value');
    await expect(page.getByTestId('connect-button')).toBeEnabled();
  });

  test('FRG-UI-029: connecting with an invalid cookie surfaces an honest error and persists nothing', async ({
    page,
  }) => {
    await page.goto('/sources');

    await page
      .getByTestId('cookie-input')
      .fill('_simpleauth_sess=definitely-not-a-valid-humble-session');
    await page.getByTestId('connect-button').click();

    // The live validation fails (bad cookie / unreachable store): an honest
    // error surfaces, the connect card stays, and no manage view appears — the
    // silent-failure UAT gap must never recur.
    await expect(page.getByTestId('connect-error')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('store-manage')).toHaveCount(0);
    await expect(page.getByTestId('connect-card')).toBeVisible();
  });
});
