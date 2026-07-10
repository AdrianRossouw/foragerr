/**
 * capture-readme-shots.ts — polished README screenshots for foragerr.
 *
 * Drives a *running* foragerr instance (backend serving the built SPA) with
 * Playwright and captures the key product screens into docs/readme-assets/.
 * It is intentionally standalone (not part of the Playwright test spine): it
 * only reads the app over HTTP, never mutates it, and can be re-run any time
 * the app is populated with a library.
 *
 * Prerequisites (the app must already be populated — see the README-assets
 * note in the repo): at least one series with covers + issue files, and, for
 * the manual-import shot, a staged library-import group under a root folder.
 *
 * Run (from the e2e/ directory). On a Node build with TypeScript stripping
 * compiled in (>= 22.6, not all distro packages):
 *
 *     BASE_URL=http://127.0.0.1:8790 \
 *       node --experimental-strip-types scripts/capture-readme-shots.ts
 *
 * On a Node build without it (ERR_NO_TYPESCRIPT), transpile first:
 *
 *     node_modules/.bin/tsc --module nodenext --target es2022 \
 *       --outDir /tmp/capture scripts/capture-readme-shots.ts
 *     BASE_URL=http://127.0.0.1:8790 node /tmp/capture/capture-readme-shots.js
 *
 * Env:
 *   BASE_URL  base URL of the running app        (default http://127.0.0.1:8790)
 *   OUT_DIR   output directory for the PNGs      (default ../docs/readme-assets)
 *   SHOTS     comma-separated subset of shot ids (default: all)
 *             ids: comics-grid, series-detail, wanted, manual-import, settings
 *   SERIES    preferred series title for the detail shot (default "Planet")
 */
import { chromium, type Page } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const BASE_URL = process.env.BASE_URL ?? 'http://127.0.0.1:8790';
const OUT_DIR = process.env.OUT_DIR ?? resolve(HERE, '../../docs/readme-assets');
const SERIES_HINT = process.env.SERIES ?? 'Planet';
const ONLY = (process.env.SHOTS ?? '')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

const VIEWPORT = { width: 1440, height: 900 };

/** Wait until every <img> on the page has decoded (naturalWidth > 0). */
async function waitForImages(page: Page, timeout = 30_000): Promise<void> {
  await page
    .waitForFunction(
      () => {
        const imgs = Array.from(document.images);
        return imgs.length === 0 || imgs.every((i) => i.complete && i.naturalWidth > 0);
      },
      undefined,
      { timeout },
    )
    .catch(() => {
      /* best-effort: a single stubborn image should not abort the run */
    });
}

/** Settle: network idle + fonts + images + a short paint delay. */
async function settle(page: Page): Promise<void> {
  // networkidle can throw on SPAs that keep sockets open (our WS) — that is
  // expected, not a failure; fonts.ready is absent on older engines. Both
  // catches tolerate exactly those cases; real page errors still surface via
  // the shot-level selector waits.
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.evaluate(() => (document as any).fonts?.ready).catch(() => {});
  await waitForImages(page);
  await page.waitForTimeout(600); // cover fade-in transitions after load
}

async function discoverSeriesId(page: Page): Promise<number | null> {
  // The in-page fetch below is same-origin, so make sure the page is on the
  // app origin first (it may still be about:blank if this is the first shot).
  if (!page.url().startsWith(BASE_URL)) {
    await page.goto(`${BASE_URL}/`, { waitUntil: 'domcontentloaded' }).catch(() => {});
  }
  const data = await page.evaluate(async (base) => {
    const r = await fetch(`${base}/api/v1/series?pageSize=200`);
    if (!r.ok) return null;
    return (await r.json()) as { records: { id: number; title: string }[] };
  }, BASE_URL);
  if (!data?.records?.length) return null;
  const hit =
    data.records.find((s) => s.title.toLowerCase().includes(SERIES_HINT.toLowerCase())) ??
    data.records[0];
  return hit.id;
}

type Shot = { id: string; run: (page: Page) => Promise<void> };

const shots: Shot[] = [
  {
    id: 'comics-grid',
    run: async (page) => {
      await page.goto(`${BASE_URL}/`, { waitUntil: 'domcontentloaded' });
      // Fail loudly: a missing grid means an empty/broken library, and a
      // silent fall-through would overwrite the committed asset with it.
      await page.waitForSelector('[data-testid="library-poster-grid"]', {
        timeout: 30_000,
      });
      await settle(page);
      await shoot(page, 'comics-grid');
    },
  },
  {
    id: 'series-detail',
    run: async (page) => {
      const id = await discoverSeriesId(page);
      if (id == null) {
        console.warn('series-detail: no series found; skipping');
        return;
      }
      await page.goto(`${BASE_URL}/series/${id}`, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('[data-testid^="issue-row-"]', {
        timeout: 30_000,
      });
      await settle(page);
      await shoot(page, 'series-detail');
    },
  },
  {
    id: 'wanted',
    run: async (page) => {
      // The interactive-search results view requires configured indexers; with
      // none configured it is an empty/error state, so we capture the Wanted
      // view (missing monitored issues) instead — the acquisition surface that
      // is meaningful without live indexers.
      await page.goto(`${BASE_URL}/wanted`, { waitUntil: 'domcontentloaded' });
      await settle(page);
      await shoot(page, 'wanted');
    },
  },
  {
    id: 'manual-import',
    run: async (page) => {
      await page.goto(`${BASE_URL}/library-import`, { waitUntil: 'domcontentloaded' });
      await settle(page);
      await shoot(page, 'manual-import');
    },
  },
  {
    id: 'settings',
    run: async (page) => {
      // Media Management: naming templates, root folders, media handling —
      // a complete settings surface that carries NO secret/credential fields.
      await page.goto(`${BASE_URL}/settings/media-management`, {
        waitUntil: 'domcontentloaded',
      });
      await settle(page);
      await shoot(page, 'settings');
    },
  },
];

async function shoot(page: Page, name: string): Promise<void> {
  const path = resolve(OUT_DIR, `${name}.png`);
  await page.screenshot({ path, fullPage: false });
  console.log(`captured ${name} -> ${path}`);
}

async function main(): Promise<void> {
  await mkdir(OUT_DIR, { recursive: true });
  const selected = ONLY.length ? shots.filter((s) => ONLY.includes(s.id)) : shots;
  // --disable-dev-shm-usage: containers often mount a small /dev/shm and the
  // renderer crashes taking full-page screenshots without it.
  const browser = await chromium.launch({ args: ['--disable-dev-shm-usage'] });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  try {
    for (const shot of selected) {
      console.log(`--- ${shot.id} ---`);
      await shot.run(page);
    }
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
