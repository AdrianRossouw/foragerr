import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import tokensCss from './tokens.css?raw';
import calendarCss from '../screens/calendar/CalendarScreen.module.css?raw';
import shellCss from '../components/AppShell.module.css?raw';
import { COMPACT_CROSSOVER_PX, COMPACT_MEDIA_QUERY } from './layout';

/**
 * FRG-UI-018 / FRG-UI-047 / FRG-UI-049 — the layout invariants a rendered DOM
 * cannot show: that the compact crossover exists exactly once so the Calendar and
 * the shell cannot disagree, that the entry titles carry no clamp or ellipsis,
 * and that real controls declare the WCAG 2.5.8 target floor. jsdom resolves no
 * custom properties and lays nothing out, so these are asserted against the
 * stylesheets themselves rather than against computed geometry (the rendered
 * bounding boxes are measured in the browser-driven tier).
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = join(HERE, '..');

function walkStyles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walkStyles(full));
    else if (entry.name.endsWith('.css')) out.push(full);
  }
  return out;
}

/** The declaration block of a single-class rule, or null when absent. */
function ruleBody(css: string, selector: string): string | null {
  const re = new RegExp(`(?:^|[},/*\\s])\\${selector}\\s*\\{([^}]*)\\}`, 'm');
  const match = re.exec(css);
  return match ? match[1] : null;
}

describe('FRG-UI-018: the compact crossover is one value', () => {
  it('FRG-UI-018 — the crossover is 900px and its media query is derived from that one constant', () => {
    expect(COMPACT_CROSSOVER_PX).toBe(900);
    // Exclusive of the crossover itself: 900px is the wide frame.
    expect(COMPACT_MEDIA_QUERY).toBe(`(max-width: ${COMPACT_CROSSOVER_PX - 0.02}px)`);
  });

  it('FRG-UI-049 — no stylesheet declares a competing width breakpoint', () => {
    // A width media query in CSS could not read the constant above, so it would
    // be a second crossover free to drift from it. The compact rules key off the
    // shell's `data-compact` attribute instead.
    //
    // SchemaForm's own 600px field-stacking breakpoint predates the crossover
    // and governs one form's internal grid, not the app frame; bringing the
    // remaining screens under one crossover is separate work (non-goal).
    const KNOWN = new Set(['src/components/schemaForm/SchemaForm.module.css']);
    const offenders: string[] = [];
    for (const file of walkStyles(SRC_ROOT)) {
      const relative = file.replace(SRC_ROOT, 'src');
      if (KNOWN.has(relative)) continue;
      const text = readFileSync(file, 'utf8');
      if (/@media[^{]*\b(?:min|max)-width\b/.test(text)) offenders.push(relative);
    }
    expect(offenders).toEqual([]);
  });

  it('FRG-UI-049 — the shell and the Calendar both switch on the same data-compact flag', () => {
    expect(shellCss).toContain("[data-compact='true']");
    expect(calendarCss).toContain("[data-compact='true']");
  });

  it('FRG-UI-049 — the drawer honours a reduced-motion preference', () => {
    expect(shellCss).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  });
});

describe('FRG-UI-018: entry titles keep their measure', () => {
  for (const selector of ['.rowTitleText', '.cardTitleText']) {
    it(`FRG-UI-018 — ${selector} neither clamps nor ellipsises the title`, () => {
      const body = ruleBody(calendarCss, selector);
      expect(body).not.toBeNull();
      expect(body).not.toMatch(/line-clamp/);
      expect(body).not.toMatch(/text-overflow/);
      // `anywhere` would break an ordinary title mid-word; `break-word` only
      // breaks a single token wider than the column.
      expect(body).not.toMatch(/overflow-wrap:\s*anywhere/);
      expect(body).toMatch(/overflow-wrap:\s*break-word/);
    });
  }

  it('FRG-UI-018 — the agenda row gives its remaining width to the title alone', () => {
    const body = ruleBody(calendarCss, '.rowFace');
    expect(body).not.toBeNull();
    // Thumbnail, title, meta, actions: only the title's column is flexible.
    expect(body).toMatch(/grid-template-columns:\s*auto minmax\(0, 1fr\) auto auto/);
  });
});

describe('FRG-UI-047: real controls declare the target floor', () => {
  it('FRG-UI-047 — the token layer pins the WCAG 2.5.8 24px floor', () => {
    expect(tokensCss).toMatch(/--layout-touch-target-min:\s*24px;/);
  });

  const CONTROL_RULES: [string, string][] = [
    ['CalendarScreen.module.css .iconBtn', 'iconBtn'],
    ['CalendarScreen.module.css .navBtn', 'navBtn'],
    ['AppShell.module.css .iconButton', 'iconButton'],
  ];

  for (const [label, className] of CONTROL_RULES) {
    it(`FRG-UI-047 — ${label} applies the shared minimum target`, () => {
      const css = className === 'iconButton' ? shellCss : calendarCss;
      const body = ruleBody(css, `.${className}`);
      expect(body).not.toBeNull();
      expect(body).toMatch(/min-width:\s*var\(--layout-touch-target-min\)/);
      expect(body).toMatch(/min-height:\s*var\(--layout-touch-target-min\)/);
    });
  }

  it('FRG-UI-047 — the calendar and shell controls carry a visible focus-visible outline', () => {
    expect(calendarCss).toMatch(/\.iconBtn:focus-visible\s*\{[^}]*outline:/);
    expect(shellCss).toMatch(/\.iconButton:focus-visible\s*\{[^}]*outline:/);
  });
});
