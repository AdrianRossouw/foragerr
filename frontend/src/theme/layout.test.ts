import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import tokensCss from './tokens.css?raw';
import calendarCss from '../screens/calendar/CalendarScreen.module.css?raw';
import shellCss from '../components/AppShell.module.css?raw';
import segmentedCss from '../components/SegmentedControl.module.css?raw';
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

  it('FRG-UI-018 — the agenda row gives its remaining width to the title and floors its measure', () => {
    const body = ruleBody(calendarCss, '.rowFace');
    expect(body).not.toBeNull();
    // Thumbnail, title, meta, actions: only the title's column is flexible, and
    // its minimum is DEFINITE — a meta track that sizes to its own content is
    // otherwise unbounded, and the flexible track is the one grid sacrifices.
    expect(body).toMatch(
      /grid-template-columns:\s*auto minmax\(min\(25ch, 100%\), 1fr\) minmax\(0, auto\) auto/,
    );
  });

  it('FRG-UI-018 — the row meta can shrink below its own content so the title floor is reachable', () => {
    // Without `min-width: 0` the meta track never goes under its min-content
    // width, and a long publisher plus a state chip is wider than the title.
    const meta = ruleBody(calendarCss, '.rowMeta');
    expect(meta).not.toBeNull();
    expect(meta).toMatch(/min-width:\s*0/);
    expect(calendarCss).toMatch(
      /\.rowMeta \.metaText\s*\{[^}]*text-overflow:\s*ellipsis/,
    );
  });

  it('FRG-UI-047 — the future-dated treatment dims artwork only, never the text that carries state', () => {
    // Ancestor opacity multiplies through every text colour inside the entry:
    // --text-secondary meta falls from 5.79:1 to 3.68:1 and the status chip from
    // 5.24:1 to 3.43:1 against the page, under the 4.5:1 WCAG 1.4.3 AA floor —
    // and that text is the only carrier of state (FRG-UI-047). axe reports
    // ancestor-opacity contrast as *incomplete*, so it cannot catch this.
    expect(ruleBody(calendarCss, '.entryFuture')).toBeNull();
    expect(calendarCss).toMatch(
      /\.entryFuture \.cover,\s*\.entryFuture \.spine\s*\{[^}]*opacity/,
    );
  });
});

describe('FRG-UI-047: real controls declare the target floor', () => {
  it('FRG-UI-047 — the token layer pins the WCAG 2.5.8 24px floor', () => {
    expect(tokensCss).toMatch(/--layout-touch-target-min:\s*24px;/);
  });

  /**
   * The stylesheets owned by the surfaces this change brings to the floor. The
   * set of RULES is derived, never listed: an enumerated allowlist cannot fail
   * for a control it does not name, which is how a 20px-tall shared segment
   * shipped past a green stylesheet test. Controls these surfaces render from
   * elsewhere are measured as rendered geometry in the browser-driven tier
   * (e2e/tests/x-a11y.spec.ts) — bringing every other screen's ~21px icon button
   * to the floor is separate work (FRG-UI-047 non-goal).
   */
  const SURFACE_STYLESHEETS: [string, string][] = [
    ['CalendarScreen.module.css', calendarCss],
    ['AppShell.module.css', shellCss],
    ['SegmentedControl.module.css', segmentedCss],
  ];

  /** `cursor: pointer` is what a stylesheet says to mean "this is a control". */
  function controlRules(css: string): { selector: string; body: string }[] {
    const out: { selector: string; body: string }[] = [];
    for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const body = match[2];
      if (!/cursor:\s*pointer/.test(body)) continue;
      // Trailing line of the selector: the preceding comment block is not it.
      const selector = match[1].trim().split('\n').pop()?.trim() ?? '';
      out.push({ selector, body });
    }
    return out;
  }

  /** A declared box at least the floor tall, by token or by literal. */
  function meetsHeightFloor(body: string): boolean {
    if (/min-height:\s*var\(--layout-touch-target-min\)/.test(body)) return true;
    const literal = /(?:min-)?height:\s*(\d+)px/.exec(body);
    return literal !== null && Number(literal[1]) >= 24;
  }

  for (const [label, css] of SURFACE_STYLESHEETS) {
    it(`FRG-UI-047 — every control rule in ${label} declares the target floor`, () => {
      const rules = controlRules(css);
      // Non-vacuity: a stylesheet whose controls stopped being recognisable
      // would otherwise pass this by finding nothing to check.
      expect(rules.length).toBeGreaterThan(0);
      const offenders = rules
        .filter((rule) => !meetsHeightFloor(rule.body))
        .map((rule) => rule.selector);
      expect(offenders).toEqual([]);
    });
  }

  it('FRG-UI-047 — the icon-only controls floor BOTH axes, not just the line box', () => {
    // A glyph-sized control has no text to widen it: 14px of icon in 4px of
    // padding is 22px square without an explicit minimum.
    for (const [css, selector] of [
      [calendarCss, '.iconBtn'],
      [calendarCss, '.navBtn'],
      [shellCss, '.iconButton'],
    ] as const) {
      const body = ruleBody(css, selector);
      expect(body).not.toBeNull();
      expect(body).toMatch(/min-width:\s*var\(--layout-touch-target-min\)/);
      expect(body).toMatch(/min-height:\s*var\(--layout-touch-target-min\)/);
    }
  });

  it('FRG-UI-047 — the calendar and shell controls carry a visible focus-visible outline', () => {
    expect(calendarCss).toMatch(/\.iconBtn:focus-visible\s*\{[^}]*outline:/);
    expect(shellCss).toMatch(/\.iconButton:focus-visible\s*\{[^}]*outline:/);
    // The nav item is the element the drawer moves focus onto (FRG-UI-049), so a
    // keyboard operator arrives on it with no indicator unless it has its own.
    expect(shellCss).toMatch(/\.navLink:focus-visible\s*\{[^}]*outline:/);
  });

  it('FRG-UI-047 — an unavailable-but-focusable control is quieted by colour, not by opacity', () => {
    // Ancestor opacity multiplies through the focus ring as well as the glyph,
    // and these controls stay focusable while unavailable (aria-disabled, not
    // disabled) — a ring under 3:1 fails WCAG 2.4.11 on the one control the
    // keyboard operator is standing on.
    const quieted = /\.iconBtn:disabled,\s*\.iconBtn\[aria-disabled='true'\]\s*\{([^}]*)\}/.exec(
      calendarCss,
    );
    expect(quieted).not.toBeNull();
    expect(quieted![1]).not.toMatch(/opacity/);
    expect(quieted![1]).toMatch(/color:\s*var\(--text-muted\)/);
    expect(ruleBody(calendarCss, '.iconBtn.iconBtnBusy')).not.toMatch(/opacity/);
  });
});
