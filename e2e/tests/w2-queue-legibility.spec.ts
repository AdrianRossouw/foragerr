import { test, expect, type Page } from '@playwright/test';

/**
 * Queue containment, measured (FRG-UI-006). The motivating dogfood report was a
 * layout one — "there's a rendering issue on the wanted queue" — and the shape
 * of it was a release name with no break opportunity in it widening the table
 * until the per-row Remove control sat past the right edge, unreachable, with
 * the whole page scrolling sideways. jsdom lays nothing out, so the vitest tier
 * can only assert the stylesheet says the right things; this is the tier that
 * can measure whether they worked.
 *
 * The ROW DATA is served by a route handler rather than seeded through the API:
 * the hermetic stack has no download client, and its only real download (the
 * in-process DDL grab in `spine.spec.ts`) imports within seconds, so there is
 * no way to hold a queue row — let alone one named by a pathological token —
 * still long enough to measure it. Everything being measured here is real: the
 * app's own bundle, stylesheet, fonts and layout in a real browser at a real
 * viewport. Only the row's existence is arranged.
 */

const WIDE = { width: 1440, height: 900 };

/**
 * A release name with NO break opportunity: no space, no hyphen, no dot. This
 * is the input class the bug was about — a name the browser cannot wrap unless
 * the stylesheet lets it break mid-token.
 */
const UNBREAKABLE_TOKEN = 'a'.repeat(180);

const QUEUE_ROW = {
  id: 90001,
  seriesId: null,
  issueId: null,
  series: null,
  issue: null,
  size: 734003200,
  sizeleft: 734003200,
  status: 'error',
  state: 'failed',
  statusMessages: ['Download failed at the client'],
  downloadId: UNBREAKABLE_TOKEN,
  protocol: 'usenet',
  downloadClient: 'example-client',
  indexer: 'example-indexer',
  outputPath: null,
  estimatedCompletion: null,
};

/** Serve exactly one pathological row for every queue read this page makes. */
async function stubPathologicalQueue(page: Page): Promise<void> {
  await page.route('**/api/v1/queue?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        page: 1,
        pageSize: 20,
        sortKey: 'added_at',
        sortDirection: 'desc',
        totalRecords: 1,
        failedRecords: 1,
        records: [QUEUE_ROW],
      }),
    });
  });
}

test('FRG-UI-006: an unbreakable release name never pushes the row actions out of reach', async ({
  page,
}) => {
  await page.setViewportSize(WIDE);
  await stubPathologicalQueue(page);
  await page.goto('/queue');

  const row = page.getByTestId(`queue-row-${QUEUE_ROW.id}`);
  await expect(row).toBeVisible();
  // Measured after the webfont swaps in: the fallback face has different
  // metrics, and a table that fits in one and not the other is not contained.
  await page.evaluate(async () => {
    await document.fonts.ready;
  });

  const measured = await page.evaluate(() => {
    // The app's only scrolling region (AppShell.module.css `.outlet`). Its
    // `overflow-y: auto` makes the horizontal axis `auto` too, so overflow
    // shows up HERE first — the document element can only exceed its client
    // width if something escapes that region entirely. Both are asserted: the
    // frame check is the user-visible symptom, the scroller check is the one
    // that can actually fail.
    const scroller = document.getElementById('main-content');
    const wrap = document.querySelector<HTMLElement>(
      '[data-testid="queue-table-wrap"]',
    );
    return {
      frameScrollWidth: document.documentElement.scrollWidth,
      frameClientWidth: document.documentElement.clientWidth,
      scrollerFound: scroller !== null,
      scrollerScrollWidth: scroller?.scrollWidth ?? 0,
      scrollerClientWidth: scroller?.clientWidth ?? 0,
      wrapFound: wrap !== null,
      wrapOverflowX: wrap === null ? '' : getComputedStyle(wrap).overflowX,
    };
  });

  expect(measured.scrollerFound, 'the scrolling region was found to measure').toBe(true);
  expect(measured.wrapFound, 'the table sits in its own scroll container').toBe(true);
  // Wide content is the container's problem, not the page's.
  expect(measured.wrapOverflowX).toBe('auto');
  expect(
    measured.frameScrollWidth,
    `frame ${measured.frameScrollWidth} vs ${measured.frameClientWidth}`,
  ).toBeLessThanOrEqual(measured.frameClientWidth + 1);
  expect(
    measured.scrollerScrollWidth,
    `content region ${measured.scrollerScrollWidth} vs ${measured.scrollerClientWidth}`,
  ).toBeLessThanOrEqual(measured.scrollerClientWidth + 1);

  // The control the bug made unreachable, in the viewport it is supposed to be in.
  const remove = row.getByRole('button', { name: `Remove ${UNBREAKABLE_TOKEN}` });
  await expect(remove).toBeVisible();
  const box = await remove.boundingBox();
  expect(box, 'the Remove control has a rendered box').not.toBeNull();
  expect(box!.x, 'Remove starts inside the viewport').toBeGreaterThanOrEqual(0);
  expect(
    box!.x + box!.width,
    `Remove ends at ${box!.x + box!.width} in a ${WIDE.width}px viewport`,
  ).toBeLessThanOrEqual(WIDE.width);
  // Reachable, not merely rendered: a control the layout has pushed under
  // another element is visible by every static measure and still unclickable.
  await remove.click();
  await expect(page.getByRole('dialog', { name: /Remove/ })).toBeVisible();
});
