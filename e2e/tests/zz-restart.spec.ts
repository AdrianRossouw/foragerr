import { test, expect, request as pwRequest } from '@playwright/test';
import { execFileSync } from 'node:child_process';

/**
 * Restart-resilience scenario (FRG-PROC-010, FRG-SCHED-002), isolated in its own
 * file (runs after the spine): it `docker restart`s the app container, which can
 * reassign the ephemeral host port, so it must never share a serial group with
 * the spine — a retry here re-discovers the port and reruns only this scenario.
 */

const BASE_URL = process.env.FORAGERR_BASE_URL ?? 'http://127.0.0.1:8789';

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

test('FRG-PROC-010 FRG-SCHED-002: library and command queue survive a container restart', async ({ page }) => {
  const container = process.env.E2E_APP_CONTAINER;
  test.skip(!container, 'no container id provided (run via e2e/run.sh)');

  // Capture pre-restart state on the current mapping.
  const api = await pwRequest.newContext({ baseURL: BASE_URL, ignoreHTTPSErrors: true });
  const series = await (await api.get('/api/v1/series?page=1&pageSize=200')).json();
  const seriesId = series.records.find((s: any) => s.cv_volume_id === 18166)?.id;
  expect(seriesId, 'the imported series exists before restart').toBeTruthy();
  const before = await (await api.get('/api/v1/command?page=1&pageSize=1')).json();
  const priorCommands = before.totalRecords;
  expect(priorCommands).toBeGreaterThan(0);
  await api.dispose();

  execFileSync('docker', ['restart', container!], { stdio: 'ignore' });

  // `docker restart` may reassign the ephemeral host port — re-discover it.
  const mapping = execFileSync('docker', ['port', container!, '8789/tcp']).toString();
  const newPort = mapping.trim().split('\n')[0].trim().split(':').pop();
  const newBase = `http://127.0.0.1:${newPort}`;

  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline && !(await healthy(newBase))) {
    await new Promise((r) => setTimeout(r, 2_000));
  }
  expect(await healthy(newBase), 'app healthy after restart').toBe(true);

  const api2 = await pwRequest.newContext({ baseURL: newBase, ignoreHTTPSErrors: true });
  // Persisted library survives the restart.
  const detail = await (await api2.get(`/api/v1/series/${seriesId}`)).json();
  expect(detail.statistics.file_count).toBeGreaterThanOrEqual(1);
  // The persisted command queue/history survives (FRG-SCHED-002).
  const after = await (await api2.get('/api/v1/command?page=1&pageSize=1')).json();
  expect(after.totalRecords).toBeGreaterThanOrEqual(priorCommands);
  await api2.dispose();

  // And the UI reconnects on the new mapping.
  await page.goto(`${newBase}/`);
  await expect(page.getByRole('link', { name: /Saga/ }).first()).toBeVisible();
});
