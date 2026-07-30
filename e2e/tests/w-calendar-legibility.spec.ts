import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import { newApiContext, until } from './helpers';
// The app's own crossover constant, not a copy of it: a second literal here
// could drift from the one the shell and the Calendar both switch on.
import { COMPACT_CROSSOVER_PX } from '../../frontend/src/theme/layout';

/**
 * Calendar legibility, measured (FRG-UI-018, FRG-UI-047, FRG-UI-049). These are
 * the assertions no jsdom test can make: axe-core does not test WCAG 2.5.8, a
 * stylesheet assertion cannot know a rendered bounding box, and `inert` focus
 * containment is not implemented outside a real browser.
 *
 * The fixture ComicVine serves a volume whose 60 issues are all store-dated on
 * one day of the CURRENT ISO week, so the weekly-pull projection's
 * library-primary half (FRG-PULL-001) fills the week the Calendar opens on with
 * no external pull source configured. The series is added with monitoring OFF so
 * seeding this week adds nothing to the wanted list and starts no search.
 *
 * Runs after `spine.spec.ts` (single worker, file order) and before
 * `x-a11y.spec.ts`, so the axe pass scans a Calendar with real rows in it.
 */

const CAL_VOLUME_ID = 6042;
const WIDE = { width: 1280, height: 900 };
/** Exactly the crossover: the width the title-measure floor is derived at. */
const AT_CROSSOVER = { width: COMPACT_CROSSOVER_PX, height: 900 };
const NARROW = { width: 600, height: 900 };

/** The WCAG 2.5.8 pointer-target floor FRG-UI-047 pins for these surfaces. */
const TARGET_FLOOR_PX = 24;
/** FRG-UI-018's per-entry vertical bound for a single-line agenda row. */
const ROW_BAND_MAX_PX = 36;
/** FRG-UI-018's title measure floor, in characters of the title's own font. */
const TITLE_MIN_CHARS = 30;

let api: APIRequestContext;

test.beforeAll(async ({ baseURL }) => {
  api = await newApiContext(baseURL!);
});

test.afterAll(async () => {
  await api?.dispose();
});

/** Add the dense-week volume (idempotent across a serial-group retry). */
async function seedDenseWeek(): Promise<number> {
  const listed = await (await api.get('/api/v1/series?page=1&pageSize=200')).json();
  const existing = listed.records?.find(
    (s: { cv_volume_id: number }) => s.cv_volume_id === CAL_VOLUME_ID,
  );
  let seriesId: number = existing?.id ?? 0;
  if (!seriesId) {
    const roots = await (await api.get('/api/v1/rootfolder')).json();
    const rootFolderId = (Array.isArray(roots) ? roots : roots.records)[0].id;
    const created = await api.post('/api/v1/series', {
      data: {
        cv_volume_id: CAL_VOLUME_ID,
        root_folder_id: rootFolderId,
        // Nothing this week is wanted or searched for: the scenarios measure
        // geometry, and a monitored 60-issue run would enqueue 60 searches.
        monitor_strategy: 'none',
        monitor_new_items: 'none',
        search_on_add: false,
      },
    });
    expect(created.ok(), `add dense-week series: ${await created.text()}`).toBe(true);
    seriesId = (await created.json()).id;
  }
  // The refresh chain populates the issues the projection then reads.
  await until(
    async () => {
      const res = await api.get(`/api/v1/series/${seriesId}`);
      if (!res.ok()) return false;
      return ((await res.json()).statistics?.issue_count ?? 0) >= 10;
    },
    { label: 'dense-week issues ingested', timeoutMs: 120_000 },
  );
  return seriesId;
}

/** Open the Calendar and wait for the seeded week's rows to be on screen. */
async function openSeededWeek(page: Page): Promise<void> {
  await page.goto('/calendar');
  await expect(page.getByTestId('week-range')).toBeVisible();
  await expect
    .poll(async () => page.getByText(/^Loading\b/i).count(), { timeout: 20_000 })
    .toBe(0);
  const entries = page.locator('[data-testid^="calendar-card-"]');
  await expect(
    entries.first(),
    'the seeded week has entries to measure',
  ).toBeVisible();
}

test.beforeAll(async () => {
  await seedDenseWeek();
});

test('FRG-UI-047: every calendar and chrome control meets the 24px target floor at both sides of the crossover', async ({
  page,
}) => {
  // Derived from what is RENDERED, not from a list of class names: a control
  // this screen inherits from a shared component is exactly the case a
  // hand-enumerated stylesheet check cannot fail for.
  const undersized: string[] = [];
  for (const viewport of [WIDE, NARROW]) {
    await page.setViewportSize(viewport);
    await openSeededWeek(page);
    // Below the crossover the chrome's nav toggle exists and must also clear the
    // floor; opening the drawer puts its own controls on screen.
    if (viewport === NARROW) {
      await expect(page.getByTestId('nav-toggle')).toBeVisible();
    }
    const controls = page.locator(
      'button:visible, a[href]:visible, select:visible, input:visible',
    );
    const count = await controls.count();
    expect(count, 'controls were found to measure').toBeGreaterThan(3);
    for (let index = 0; index < count; index += 1) {
      const control = controls.nth(index);
      const box = await control.boundingBox();
      if (box === null) continue;
      if (box.width < TARGET_FLOOR_PX || box.height < TARGET_FLOOR_PX) {
        const name =
          (await control.getAttribute('aria-label')) ??
          (await control.getAttribute('data-testid')) ??
          (await control.textContent()) ??
          '(unnamed)';
        undersized.push(
          `${viewport.width}px: "${name.trim().slice(0, 40)}" ` +
            `${box.width.toFixed(1)}x${box.height.toFixed(1)}`,
        );
      }
    }
  }
  expect(undersized, `controls under ${TARGET_FLOOR_PX}px`).toEqual([]);
});

test('FRG-UI-018: an agenda row keeps ~30 characters of title measure at the crossover width', async ({
  page,
}) => {
  // The narrowest width that still renders rows is where the measure is worst,
  // and the character count is measured in the title's OWN font rather than
  // assumed from a pixel figure.
  await page.setViewportSize(AT_CROSSOVER);
  await openSeededWeek(page);

  const measured = await page.evaluate(() => {
    const title = document.querySelector<HTMLElement>(
      '[data-mode="row"] [class*="rowTitleText"]',
    );
    if (title === null) return null;
    const style = getComputedStyle(title);
    const probe = document.createElement('span');
    probe.style.position = 'absolute';
    probe.style.visibility = 'hidden';
    probe.style.whiteSpace = 'pre';
    probe.style.font = style.font;
    probe.style.fontFamily = style.fontFamily;
    probe.style.fontSize = style.fontSize;
    probe.style.fontWeight = style.fontWeight;
    probe.style.letterSpacing = style.letterSpacing;
    // 30 characters of ordinary mixed-case text, not 30 of the widest glyph.
    probe.textContent = 'Chronicles of the Meridian Exp';
    document.body.appendChild(probe);
    const perThirty = probe.getBoundingClientRect().width;
    probe.remove();
    return {
      titleWidth: title.getBoundingClientRect().width,
      thirtyCharsWidth: perThirty,
      overflowing:
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    };
  });

  expect(measured, 'a row title to measure').not.toBeNull();
  const { titleWidth, thirtyCharsWidth, overflowing } = measured!;
  const chars = (titleWidth / thirtyCharsWidth) * TITLE_MIN_CHARS;
  // The measurement itself is the evidence this scenario exists to produce.
  console.log(
    `[FRG-UI-018] title measure at ${AT_CROSSOVER.width}px: ` +
      `${titleWidth.toFixed(1)}px = ~${chars.toFixed(1)} characters`,
  );
  expect(
    chars,
    `title measure ${titleWidth.toFixed(1)}px = ~${chars.toFixed(1)} characters`,
  ).toBeGreaterThanOrEqual(TITLE_MIN_CHARS);
  // The floor must not have been bought with a horizontally scrolling frame.
  expect(overflowing, 'the frame does not scroll sideways').toBe(false);
});

test('FRG-UI-018: a dense day holds every entry inside the per-entry vertical bound', async ({
  page,
}) => {
  await page.setViewportSize(WIDE);
  await openSeededWeek(page);

  const density = await page.evaluate(() => {
    const rows = Array.from(
      document.querySelectorAll<HTMLElement>('[data-mode="row"]'),
    );
    const day = rows[0]?.closest('[data-testid^="calendar-day-"]');
    const bands = rows.map((row) => row.getBoundingClientRect().height);
    return {
      count: rows.length,
      maxBand: Math.max(...bands),
      dayHeight: day?.getBoundingClientRect().height ?? 0,
      viewportHeight: window.innerHeight,
    };
  });

  console.log(
    `[FRG-UI-018] ${density.count} entries, tallest band ` +
      `${density.maxBand.toFixed(1)}px, day ${density.dayHeight.toFixed(0)}px = ` +
      `${(density.dayHeight / density.viewportHeight).toFixed(2)} viewport heights`,
  );
  expect(density.count, 'a dense day was seeded').toBeGreaterThanOrEqual(30);
  expect(
    density.maxBand,
    `tallest entry band across ${density.count} entries`,
  ).toBeLessThanOrEqual(ROW_BAND_MAX_PX);
  // The bound is what makes the day readable: at this band a 60-entry day is
  // roughly two viewport heights rather than the four the card grid produced.
  const screenfuls = (density.count * density.maxBand) / density.viewportHeight;
  expect(screenfuls, `${density.count} entries in viewport heights`).toBeLessThan(3);
});

test('FRG-UI-049: the open nav drawer contains Tab and Shift+Tab', async ({ page }) => {
  // `aria-modal="true"` is only honest if the outside world is unreachable; the
  // containment is native (`inert` on the rest of the frame), and jsdom does not
  // implement it, so this is the tier that can prove it.
  await page.setViewportSize(NARROW);
  await page.goto('/calendar');
  await page.getByTestId('nav-toggle').click();
  const drawer = page.getByTestId('nav-drawer');
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveAttribute('aria-modal', 'true');

  /**
   * Where focus is: `null` for inside the drawer, `'document'` when the tab
   * order has wrapped through the document root (no page element holds focus,
   * which is containment working, not a leak), or the escapee's own markup.
   */
  const focusEscapee = () =>
    page.evaluate(() => {
      const drawerEl = document.querySelector('[data-testid="nav-drawer"]');
      const active = document.activeElement;
      if (
        active === null ||
        active === document.body ||
        active === document.documentElement
      ) {
        return 'document';
      }
      return drawerEl?.contains(active) === true
        ? null
        : `${active.tagName}: ${active.outerHTML.slice(0, 70)}`;
    });

  expect(await focusEscapee(), 'focus enters the drawer on open').toBeNull();
  // More presses than the drawer has stops, in both directions, so a leak into
  // the header's quick-search or the Calendar's own controls has to show up.
  const walk: (string | null)[] = [];
  for (let press = 0; press < 40; press += 1) {
    await page.keyboard.press('Tab');
    walk.push(await focusEscapee());
  }
  for (let press = 0; press < 40; press += 1) {
    await page.keyboard.press('Shift+Tab');
    walk.push(await focusEscapee());
  }
  expect(
    walk.filter((where) => where !== null && where !== 'document'),
    'elements outside the drawer that received focus',
  ).toEqual([]);
  // Non-vacuity: the walk really did move through the drawer's own controls.
  expect(walk.filter((where) => where === null).length).toBeGreaterThan(10);

  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);
  expect(await page.locator('[inert]').count(), 'containment released').toBe(0);
});
