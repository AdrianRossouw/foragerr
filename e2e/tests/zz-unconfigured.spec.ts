import { test, expect, request as pwRequest } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

/**
 * Unconfigured-key negative path (FRG-PROC-010, FRG-UI-005): a stack with NO
 * ComicVine API key must surface an actionable credential error on Add Series,
 * never the plain "no results" state (the silent-401 UAT gap, 2026-07-06).
 *
 * Runs LAST (after zz-restart, alphabetical file order): it recreates the app
 * container with an explicitly EMPTY `E2E_CV_API_KEY` — compose.yaml's
 * `${E2E_CV_API_KEY-e2e-example-key}` (dash form) passes empty through while
 * unset still yields the fixture key — so every earlier scenario keeps the
 * configured key. The recreate reassigns the ephemeral host port, so like
 * zz-restart it re-discovers the mapping and never shares a serial group with
 * the spine. No restore afterwards: run.sh's teardown is `compose down` and
 * the report generator only reads results.json, neither needs the configured
 * container back (a retry re-runs the idempotent recreate).
 */

const COMPOSE_FILE = fileURLToPath(new URL('../compose.yaml', import.meta.url));
// Mirror run.sh's invocation: docker compose -f e2e/compose.yaml -p foragerr-e2e
const COMPOSE = ['compose', '-f', COMPOSE_FILE, '-p', 'foragerr-e2e'];

async function healthy(base: string): Promise<boolean> {
  const ctx = await pwRequest.newContext({ baseURL: base, ignoreHTTPSErrors: true });
  try {
    return (await ctx.get('/health')).status() === 200;
  } catch {
    return false;
  } finally {
    await ctx.dispose();
  }
}

test('FRG-PROC-010 FRG-UI-005: an unconfigured ComicVine key surfaces an actionable credential error, not "no results"', async ({ page }) => {
  // The compose project env (FORAGERR_E2E_RUN et al.) only exists under run.sh.
  test.skip(!process.env.FORAGERR_E2E_RUN, 'no compose run dir provided (run via e2e/run.sh)');

  // Recreate ONLY the app container with an explicitly EMPTY key. `--no-deps`
  // leaves mockhub untouched; config/library bind mounts persist, so only the
  // credential changes. Idempotent: a retry recreates to the same state.
  execFileSync('docker', [...COMPOSE, 'up', '-d', '--force-recreate', '--no-deps', 'foragerr'], {
    env: { ...process.env, E2E_CV_API_KEY: '' },
    stdio: 'ignore',
  });

  // The recreate reassigns the ephemeral host port — re-discover it.
  const mapping = execFileSync('docker', [...COMPOSE, 'port', 'foragerr', '8789'], {
    env: { ...process.env, E2E_CV_API_KEY: '' },
  }).toString();
  const newPort = mapping.trim().split('\n')[0].trim().split(':').pop();
  const newBase = `http://127.0.0.1:${newPort}`;

  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline && !(await healthy(newBase))) {
    await new Promise((r) => setTimeout(r, 2_000));
  }
  expect(await healthy(newBase), 'app healthy after keyless recreate').toBe(true);

  // Drive the REAL UI: search on Add Series exactly as a user would.
  await page.goto(`${newBase}/add`);
  await page.getByRole('searchbox', { name: 'Search ComicVine' }).fill('saga');
  await page.getByRole('button', { name: 'Search', exact: true }).click();

  // The actionable credential error renders (mockhub 401s the keyless request,
  // the API maps it to 503 naming the key, the UI points at Settings)...
  await expect(page.getByRole('alert')).toHaveText(
    'ComicVine API key missing or invalid — check Settings.',
  );
  // ...and the outcome is NOT presented as a genuinely-empty result.
  await expect(page.getByText(/No volumes found/)).toHaveCount(0);
});
