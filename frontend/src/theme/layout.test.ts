import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import tokensCss from './tokens.css?raw';
import calendarCss from '../screens/calendar/CalendarScreen.module.css?raw';
import shellCss from '../components/AppShell.module.css?raw';
import segmentedCss from '../components/SegmentedControl.module.css?raw';
import sourcesCss from '../screens/sources/sources.module.css?raw';
import {
  COMPACT_CROSSOVER_PX,
  COMPACT_MEDIA_QUERY,
  TOUCH_TARGET_MIN_PX,
} from './layout';

/**
 * FRG-UI-018 / FRG-UI-029 / FRG-UI-047 / FRG-UI-049 — the layout invariants a
 * rendered DOM cannot show: that the compact crossover exists exactly once so the
 * Calendar and the shell cannot disagree, that the entry titles carry no clamp or
 * ellipsis, that the six-segment filter row wraps rather than overflowing its
 * column, and that real controls declare the WCAG 2.5.8 target floor. jsdom resolves no
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

  it('FRG-UI-018 — the shelf row gives its remaining width to the content block and floors the title measure', () => {
    const body = ruleBody(calendarCss, '.rowFace');
    expect(body).not.toBeNull();
    // Cover, content block, rail: only the content column is flexible, and its
    // minimum is DEFINITE — a track that sizes to its own content is otherwise
    // unbounded, and the flexible track is the one grid sacrifices.
    expect(body).toMatch(
      /grid-template-columns:\s*auto minmax\(min\(25ch, 100%\), 1fr\) auto/,
    );
    // No fourth track: the meta moved INSIDE the content block, so nothing
    // competes with the title for the row's horizontal space any more.
    expect(body).not.toMatch(/1fr\)\s*minmax/);
  });

  it('FRG-UI-018 — the row meta and description yield to the title floor rather than the reverse', () => {
    // Without `min-width: 0` neither the content block nor its meta line goes
    // under its own min-content width, and the title's definite minimum then
    // overflows the row instead of being honoured.
    for (const selector of ['.rowBody', '.rowMeta']) {
      const body = ruleBody(calendarCss, selector);
      expect(body).not.toBeNull();
      expect(body).toMatch(/min-width:\s*0/);
    }
    // The creator line ellipsises and the description clamps; the title above
    // them does neither (asserted per-selector above).
    expect(ruleBody(calendarCss, '.rowCreators')).toMatch(
      /text-overflow:\s*ellipsis/,
    );
    expect(ruleBody(calendarCss, '.rowDeck')).toMatch(/line-clamp:\s*2/);
  });

  it('FRG-UI-018 — the shelf cover sets the row rhythm at approximately 110px', () => {
    // The cover is the row's tallest element, so its height plus the row
    // face's vertical padding plus the `.row` hairline `border-bottom` IS the
    // entry's vertical rhythm — the ~110px ceiling a single-line title must
    // stay under. The border is a real pixel of the rendered band: a sum that
    // omitted it would let the padding alone erode this test's own margin.
    const cover = ruleBody(calendarCss, '.thumbRow');
    expect(cover).not.toBeNull();
    expect(cover).toMatch(/width:\s*66px/);
    expect(cover).toMatch(/height:\s*99px/);
    const face = ruleBody(calendarCss, '.rowFace') as string;
    const padding = /padding:\s*(\d+)px/.exec(face);
    expect(padding).not.toBeNull();
    const row = ruleBody(calendarCss, '.row') as string;
    const border = /border-bottom:\s*(\d+)px/.exec(row);
    expect(border).not.toBeNull();
    const band = 99 + 2 * Number(padding![1]) + Number(border![1]);
    expect(band).toBeLessThanOrEqual(110);
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
  it('FRG-UI-047 — the token layer pins the WCAG 2.5.8 target floor', () => {
    expect(tokensCss).toMatch(
      new RegExp(`--layout-touch-target-min:\\s*${TOUCH_TARGET_MIN_PX}px;`),
    );
  });

  /**
   * The stylesheets owned by the surfaces this change brings to the floor. The
   * set of RULES is derived from `cursor: pointer` rather than listed, so a
   * control added to one of these stylesheets is swept without being named —
   * an enumerated allowlist is how a 20px-tall shared segment shipped past a
   * green stylesheet test.
   *
   * The sweep reaches DECLARED-cursor controls only. An anchor takes its pointer
   * cursor from the UA and a control rendered by a shared component declares its
   * box in that component's own stylesheet, so neither appears here; those are
   * enforced as rendered geometry in the browser-driven tier
   * (e2e/tests/w-calendar-legibility.spec.ts, e2e/tests/x-a11y.spec.ts), which
   * measures whatever is on screen. `.navLink` is exactly that case, and the
   * selectors named explicitly below are the icon-only controls whose WIDTH this
   * height sweep cannot speak to. Bringing every other screen's ~21px icon
   * button to the floor is separate work (FRG-UI-047 non-goal).
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
    return literal !== null && Number(literal[1]) >= TOUCH_TARGET_MIN_PX;
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

describe('FRG-UI-029: the filter row gives rather than overflows', () => {
  it('FRG-UI-029 — the segmented track wraps and is bounded by its column', () => {
    // Six scopes (All/New/Matched/Ignored/Duplicates/Non-comic), each carrying
    // a count, exceed a narrow column's width. An inline-flex track that can
    // neither wrap nor shrink resolves that by rendering its last segments off
    // the page — and Non-comic, the scope the whole non-comic model depends on
    // being reachable, is the last one. No width media query is involved (the
    // crossover above is the only breakpoint): wrapping is width-driven.
    const body = ruleBody(segmentedCss, '.group');
    expect(body).not.toBeNull();
    expect(body).toMatch(/flex-wrap:\s*wrap/);
    expect(body).toMatch(/max-width:\s*100%/);
    // Wrapping is BETWEEN segments: a label that broke across two lines inside
    // one segment would split a count off its scope name.
    expect(ruleBody(segmentedCss, '.segment')).toMatch(/white-space:\s*nowrap/);
  });

  it('FRG-UI-029 — the sources filter row lets the track wrap inside it', () => {
    const body = ruleBody(sourcesCss, '.filters');
    expect(body).not.toBeNull();
    expect(body).toMatch(/flex-wrap:\s*wrap/);
    // A flex item's default `min-width: auto` floors it at its content width,
    // so the track could not shrink to the row no matter what it allows.
    expect(body).toMatch(/min-width:\s*0/);
  });
});
