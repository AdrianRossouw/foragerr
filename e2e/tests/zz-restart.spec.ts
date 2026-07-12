import { test, expect, request as pwRequest } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { newApiContext } from './helpers';

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

  // Capture pre-restart state on the current mapping. We record CONCRETE
  // identities (specific row ids), not just counts: a background job that wiped
  // and rebuilt the tables could satisfy a bare "count >= prior" while losing
  // the very rows that are supposed to persist. Persistence means THESE rows
  // survive by identity.
  const api = await newApiContext(BASE_URL);
  const series = await (await api.get('/api/v1/series?page=1&pageSize=200')).json();
  const seriesId = series.records.find((s: any) => s.cv_volume_id === 18166)?.id;
  expect(seriesId, 'the imported series exists before restart').toBeTruthy();

  // Concrete library evidence: the specific issue-file id the OPDS acquisition
  // feed exposes for this series. A table wipe cannot reproduce this exact id.
  const beforeAcq = await (await api.get(`/opds/series/${seriesId}`)).text();
  const priorFileId = beforeAcq.match(/\/opds\/file\/(\d+)/)?.[1];
  expect(priorFileId, 'an issue-file id exists before restart').toBeTruthy();

  // Concrete command evidence: capture the specific command row ids (and names)
  // that must survive by identity — not merely be replaced by a same-sized set
  // of freshly-scheduled rows.
  const before = await (await api.get('/api/v1/command?page=1&pageSize=200')).json();
  const priorCommands = before.totalRecords;
  expect(priorCommands).toBeGreaterThan(0);
  const priorCommandRows: Array<{ id: number; name: string }> = (before.records ?? [])
    .filter((c: any) => c?.id != null)
    .map((c: any) => ({ id: c.id, name: c.name }));
  expect(priorCommandRows.length, 'concrete command rows captured').toBeGreaterThan(0);
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

  const api2 = await newApiContext(newBase);
  // Persisted library survives the restart — asserted by identity: the SAME
  // issue-file id is still served from the series' OPDS acquisition feed.
  const detail = await (await api2.get(`/api/v1/series/${seriesId}`)).json();
  expect(detail.statistics.file_count).toBeGreaterThanOrEqual(1);
  const afterAcq = await (await api2.get(`/opds/series/${seriesId}`)).text();
  const afterFileIds = new Set(
    [...afterAcq.matchAll(/\/opds\/file\/(\d+)/g)].map((m) => m[1]),
  );
  expect(
    afterFileIds.has(priorFileId!),
    `the same issue-file id (${priorFileId}) survives restart`,
  ).toBe(true);

  // The persisted command queue/history survives (FRG-SCHED-002) — asserted by
  // identity: every pre-restart command row id is still present. New rows from
  // background scheduling may appear, but the captured ones must NOT vanish (a
  // count-only check would pass a wipe-and-repopulate).
  const after = await (await api2.get('/api/v1/command?page=1&pageSize=200')).json();
  const afterCommandIds = new Set<number>(
    (after.records ?? []).map((c: any) => c.id),
  );
  for (const row of priorCommandRows) {
    expect(
      afterCommandIds.has(row.id),
      `command ${row.id} (${row.name}) survives restart`,
    ).toBe(true);
  }
  await api2.dispose();

  // And the UI reconnects on the new mapping.
  await page.goto(`${newBase}/`);
  await expect(page.getByRole('link', { name: /Saga/ }).first()).toBeVisible();
});
