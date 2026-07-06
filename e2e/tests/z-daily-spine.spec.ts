import { test, expect, request as pwRequest, type APIRequestContext } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { nudgeImport, until } from './helpers';

/**
 * Daily-spine assertions deferred from m2-daily-surfaces (ch4) to this change
 * (FRG-PROC-010). The spine (spine.spec.ts) already drives a real
 * grab -> download -> import of Saga #1 through the ASSEMBLED slice; this file
 * seeds nothing of its own — it OBSERVES that assembled state through the
 * daily-use surfaces the ch4 tasks shipped but could not yet exercise
 * end-to-end:
 *
 *  (a) History (FRG-API-011 / FRG-UI-010) renders the `grabbed` and `imported`
 *      rows for the download, and the two rows share ONE downloadId — the
 *      single-source feed joining a grab to its import.
 *  (b) Wanted/Missing (FRG-API-012 / FRG-UI-011) lists Saga #2 — a monitored,
 *      published, still-fileless issue (the spine imported only #1) — proving
 *      the derived-missing list surfaces a genuinely wanted issue.
 *  (c) OPDS Recent (FRG-OPDS-013 / FRG-OPDS-005) advertises an acquisition link
 *      for the imported issue whose bytes are the exact library file.
 *
 * The grab->import chain these assert on is entirely the spine's, produced
 * through existing APIs/fixtures (the download area writes `grabbed` with a
 * downloadId at grab time; the importer writes `imported` with the SAME
 * downloadId). No fixture or backend seeding was added for this file.
 *
 * Named `z-*` so it runs AFTER the spine and the library-import journey
 * (alphabetical, one worker) but BEFORE the container-mutating `zz-*` specs
 * (restart / keyless recreate) that reassign the ephemeral host port — it reads
 * the assembled state on the original FORAGERR_BASE_URL.
 */

const BASE_URL = process.env.FORAGERR_BASE_URL ?? 'http://127.0.0.1:8789';
const RUN_DIR = process.env.FORAGERR_E2E_RUN ?? '';
const CBZ_SOURCE = RUN_DIR ? path.join(RUN_DIR, 'data', 'saga-001.cbz') : '';

// The Saga fixture volume the spine adds (mock_server.py CV_VOLUME_ID). Its #1
// is grabbed+imported by the spine; #2 stays monitored/published/fileless.
const SAGA_CV_VOLUME_ID = 18166;

const COMIC_MIME = 'application/vnd.comicbook+zip';
// The OPDS 1.2 feed media type the backend emits — assert the FULL base type +
// profile + kind param, not a bare substring a plain XML response could fake
// (mirrors the spine's expectOpdsFeedType).
const OPDS_BASE = 'application/atom+xml';
const OPDS_PROFILE = 'profile=opds-catalog';

function expectOpdsFeedType(contentType: string | undefined, kind: 'navigation' | 'acquisition') {
  expect(contentType, 'OPDS content-type present').toBeTruthy();
  expect(contentType).toContain(OPDS_BASE);
  expect(contentType).toContain(OPDS_PROFILE);
  expect(contentType).toContain(`kind=${kind}`);
}

let api: APIRequestContext;
// The spine-added Saga series id, resolved once from the assembled state.
let sagaId = 0;

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  api = await pwRequest.newContext({ baseURL: BASE_URL, ignoreHTTPSErrors: true });
  // The spine has already added Saga and imported #1; resolve its id from the
  // real API rather than sharing the spine module's state (separate file).
  sagaId = await until(
    async () => {
      const list = await (await api.get('/api/v1/series?page=1&pageSize=200')).json();
      return list.records.find((r: any) => r.cv_volume_id === SAGA_CV_VOLUME_ID)?.id ?? false;
    },
    { label: 'the spine-added Saga series', timeoutMs: 30_000 },
  );
});

test.afterAll(async () => {
  await api.dispose();
});

test('FRG-PROC-010 FRG-API-011: History shows the grabbed and imported rows sharing a downloadId', async ({ page }) => {
  test.skip(!RUN_DIR, 'no compose run dir provided (run via e2e/run.sh)');

  // Nudge any still-in-flight import to completion, then read the single-source
  // feed as the API's source of truth for the download identity that joins the
  // grab to its import.
  await until(
    async () => {
      await nudgeImport(api);
      const grabbed = await (
        await api.get(`/api/v1/history?eventType=grabbed&seriesId=${sagaId}&pageSize=200`)
      ).json();
      const imported = await (
        await api.get(`/api/v1/history?eventType=imported&seriesId=${sagaId}&pageSize=200`)
      ).json();
      return grabbed.records.length > 0 && imported.records.length > 0 ? true : false;
    },
    { label: 'the grab and import history rows for Saga', timeoutMs: 60_000 },
  );

  const grabbed = await (
    await api.get(`/api/v1/history?eventType=grabbed&seriesId=${sagaId}&pageSize=200`)
  ).json();
  const imported = await (
    await api.get(`/api/v1/history?eventType=imported&seriesId=${sagaId}&pageSize=200`)
  ).json();
  const grabRow = grabbed.records[0];
  const importRow = imported.records[0];
  expect(grabRow.downloadId, 'the grab row carries a downloadId').toBeTruthy();
  expect(importRow.downloadId, 'the import row carries a downloadId').toBeTruthy();
  // The single-source feed joins the grab to its import by ONE download identity.
  expect(importRow.downloadId).toBe(grabRow.downloadId);

  // The real History screen renders both events. Filter to each type (the feed
  // grows with every run step; filtering keeps the assertion independent of how
  // many newer rows exist) and assert the specific row is on screen with its
  // chip label.
  await page.goto('/history');
  const filter = page.getByRole('combobox', { name: 'Filter by event type' });

  await filter.selectOption('grabbed');
  const grabbedRow = page.getByTestId(`history-row-${grabRow.id}`);
  await expect(grabbedRow).toBeVisible();
  await expect(grabbedRow.getByText('Grabbed', { exact: true })).toBeVisible();

  await filter.selectOption('imported');
  const importedRow = page.getByTestId(`history-row-${importRow.id}`);
  await expect(importedRow).toBeVisible();
  await expect(importedRow.getByText('Imported', { exact: true })).toBeVisible();
});

test('FRG-PROC-010 FRG-API-012: Wanted lists a monitored, published, fileless issue', async ({ page }) => {
  test.skip(!RUN_DIR, 'no compose run dir provided (run via e2e/run.sh)');

  // Saga #2 is monitored + published (2012 cover/store date) + never downloaded,
  // so the derived-missing query surfaces it (the spine imported only #1).
  const wanted = await (await api.get('/api/v1/wanted/missing?pageSize=200')).json();
  const sagaMissing = wanted.records.find(
    (r: any) => r.series_id === sagaId && r.issue_number === '2',
  );
  expect(sagaMissing, 'Saga #2 is in the derived-missing list').toBeTruthy();
  expect(sagaMissing.monitored, 'the missing issue is monitored').toBe(true);

  // The real Wanted/Missing screen renders that row with its series link + the
  // verbatim string issue number.
  await page.goto('/wanted');
  const row = page.getByTestId(`wanted-row-${sagaMissing.id}`);
  await expect(row).toBeVisible();
  await expect(row.getByRole('link', { name: 'Saga' })).toBeVisible();
  await expect(row.getByText('#2', { exact: true })).toBeVisible();
});

test('FRG-PROC-010 FRG-OPDS-013: OPDS Recent serves the imported issue file bytes', async () => {
  test.skip(!RUN_DIR, 'no compose run dir provided (run via e2e/run.sh)');

  // The imported issue's acquisition link, taken from Saga's own feed (Saga-only,
  // so unambiguous), must ALSO be advertised by the Recent Additions feed.
  const sagaAcq = await api.get(`/opds/series/${sagaId}`);
  const sagaFileHref = (await sagaAcq.text()).match(/\/opds\/file\/\d+/)?.[0];
  expect(sagaFileHref, "Saga's acquisition file link").toBeTruthy();

  const recent = await api.get('/opds/recent');
  expect(recent.status()).toBe(200);
  expectOpdsFeedType(recent.headers()['content-type'], 'acquisition');
  const recentText = await recent.text();
  expect(recentText).toContain(COMIC_MIME);
  // Recent Additions advertises the imported issue by the SAME file link.
  expect(recentText, 'Recent advertises the imported issue').toContain(sagaFileHref);

  // Following that acquisition link serves the correct comic MIME and the exact
  // library bytes (import moves, never repackages — byte-identical to the source).
  const download = await api.get(sagaFileHref!);
  expect(download.status()).toBe(200);
  expect(download.headers()['content-type']).toContain(COMIC_MIME);
  const body = Buffer.from(await download.body());
  expect(body.equals(readFileSync(CBZ_SOURCE))).toBe(true);
});
