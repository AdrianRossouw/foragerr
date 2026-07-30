import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import { newApiContext, until } from './helpers';
// The app's own layout constants, not copies of them: a second literal here
// could drift from the values the shell, the Calendar and the token layer share.
import {
  COMPACT_CROSSOVER_PX,
  TOUCH_TARGET_MIN_PX,
} from '../../frontend/src/theme/layout';

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

/** FRG-UI-018's per-entry vertical bound for a single-line agenda row. */
const ROW_BAND_MAX_PX = 36;
/** FRG-UI-018's title measure floor, in characters of the title's own font. */
const TITLE_MIN_CHARS = 30;

let api: APIRequestContext;

test.beforeAll(async ({ baseURL }) => {
  api = await newApiContext(baseURL!);
  await seedDenseWeek();
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
    // floor, and the drawer is opened so its own nav items are on screen to be
    // measured — closed, they are not rendered at all.
    if (viewport === NARROW) {
      await expect(page.getByTestId('nav-toggle')).toBeVisible();
      await page.getByTestId('nav-toggle').click();
      await expect(page.getByTestId('nav-drawer')).toBeVisible();
    }
    // One round-trip for the whole screen: a per-control `boundingBox()` plus
    // three `getAttribute()` calls is four protocol round-trips per control, and
    // a seeded week renders hundreds of them.
    const measured = await page.evaluate(() => {
      const controls = Array.from(
        document.querySelectorAll<HTMLElement>(
          'button, a[href], select, input',
        ),
      );
      return controls
        // Playwright's own `:visible` predicate, in one expression: a non-empty
        // bounding box and no `visibility: hidden`. Both halves are needed — a
        // zero-area control and a hidden one are each unpointable, and a floor
        // that counted them would fail on controls no operator can reach.
        .map((control) => ({ control, box: control.getBoundingClientRect() }))
        .filter(
          ({ control, box }) =>
            box.width > 0 &&
            box.height > 0 &&
            getComputedStyle(control).visibility !== 'hidden',
        )
        .map(({ control, box }) => ({
          w: box.width,
          h: box.height,
          name:
            control.getAttribute('aria-label') ??
            control.getAttribute('data-testid') ??
            control.textContent ??
            '(unnamed)',
        }));
    });
    expect(measured.length, 'controls were found to measure').toBeGreaterThan(3);
    for (const { w, h, name } of measured) {
      if (w < TOUCH_TARGET_MIN_PX || h < TOUCH_TARGET_MIN_PX) {
        undersized.push(
          `${viewport.width}px: "${name.trim().slice(0, 40)}" ` +
            `${w.toFixed(1)}x${h.toFixed(1)}`,
        );
      }
    }
  }
  expect(undersized, `controls under ${TOUCH_TARGET_MIN_PX}px`).toEqual([]);
});

test('FRG-UI-018: an agenda row keeps ~30 characters of title measure at the crossover width', async ({
  page,
}) => {
  // The narrowest width that still renders rows is where the measure is worst,
  // and the character count is measured in the title's OWN font rather than
  // assumed from a pixel figure.
  await page.setViewportSize(AT_CROSSOVER);
  await openSeededWeek(page);
  // Text measured before the webfont has swapped in is measured in the fallback
  // face, and the character count derived from it describes a font the operator
  // never sees.
  await page.evaluate(async () => {
    await document.fonts.ready;
  });

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
    // The app's ONLY scrolling region (AppShell.module.css `.outlet`): its
    // `overflow-y: auto` makes the horizontal axis `auto` too, so a screen wide
    // enough to scroll sideways scrolls HERE and the document element's own
    // scrollWidth can never grow past its client width.
    const scroller = document.getElementById('main-content');
    return {
      titleWidth: title.getBoundingClientRect().width,
      thirtyCharsWidth: perThirty,
      scrollerFound: scroller !== null,
      scrollerOverflow:
        scroller !== null && scroller.scrollWidth > scroller.clientWidth,
      frameOverflow:
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    };
  });

  expect(measured, 'a row title to measure').not.toBeNull();
  const { titleWidth, thirtyCharsWidth, scrollerFound } = measured!;
  // A zero-width probe would make every ratio below Infinity and pass this
  // scenario without measuring anything.
  expect(thirtyCharsWidth, 'the 30-character probe has a width').toBeGreaterThan(0);
  const chars = (titleWidth / thirtyCharsWidth) * TITLE_MIN_CHARS;
  expect(
    chars,
    `title measure ${titleWidth.toFixed(1)}px = ~${chars.toFixed(1)} characters ` +
      `at ${AT_CROSSOVER.width}px`,
  ).toBeGreaterThanOrEqual(TITLE_MIN_CHARS);
  // The floor must not have been bought with a sideways-scrolling frame.
  expect(scrollerFound, 'the scrolling region was found to measure').toBe(true);
  expect(measured!.scrollerOverflow, 'the content region does not scroll sideways').toBe(
    false,
  );
  expect(measured!.frameOverflow, 'the frame does not scroll sideways').toBe(false);
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

  /**
   * Walk the tab order one direction, recording where each press landed. One
   * press more than asked for, so the LAST recorded landing still has a
   * successor to be judged against.
   */
  const walkFocus = async (key: 'Tab' | 'Shift+Tab', presses: number) => {
    const seen: (string | null)[] = [];
    for (let press = 0; press <= presses; press += 1) {
      await page.keyboard.press(key);
      seen.push(await focusEscapee());
    }
    return seen;
  };

  // More presses than the drawer has stops, in both directions, so a leak into
  // the header's quick-search or the Calendar's own controls has to show up.
  const forward = await walkFocus('Tab', 40);
  const backward = await walkFocus('Shift+Tab', 40);
  expect(
    [...forward, ...backward].filter(
      (where) => where !== null && where !== 'document',
    ),
    'elements outside the drawer that received focus',
  ).toEqual([]);

  // A wrap through the document root is containment working ONLY if the very
  // next press is back inside the drawer. Focus lost to the body looks identical
  // for one press and then never comes back, so accepting 'document' anywhere in
  // the walk is what would let that pass.
  const stranded: string[] = [];
  for (const [label, segment] of [
    ['Tab', forward],
    ['Shift+Tab', backward],
  ] as const) {
    segment.slice(0, -1).forEach((where, index) => {
      if (where === 'document' && segment[index + 1] !== null) {
        stranded.push(`${label} press ${index + 1} -> ${segment[index + 1]}`);
      }
    });
  }
  expect(stranded, 'wraps after which focus did not return into the drawer').toEqual(
    [],
  );
  // Non-vacuity: the walk really did move through the drawer's own controls.
  expect(
    [...forward, ...backward].filter((where) => where === null).length,
  ).toBeGreaterThan(10);

  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);
  expect(await page.locator('[inert]').count(), 'containment released').toBe(0);
  // The dismissal returns focus to the control that opened the drawer. Only a
  // real browser can prove this: the restore has to outlive the commit that
  // releases the containment, because a focus() call into an inert subtree is
  // silently ignored — and jsdom ignores `inert` instead.
  await expect(page.getByTestId('nav-toggle')).toBeFocused();
});
