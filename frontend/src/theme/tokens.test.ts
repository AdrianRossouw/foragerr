import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import tokensCss from './tokens.css?raw';
import { PUBLISHER_ACCENT_DEFAULT } from './palettes';

/**
 * FRG-UI-002 — token definitions parsed straight from tokens.css.
 * Covers: "tokens defined once with theme-neutral names", "token-name audit
 * rejects brand-named tokens", the owner's handoff palette values, and the
 * single-palette-source scan (design decision 1: the core palette lives only in
 * the token layer + the publisher/format data maps, never hardcoded in a
 * component).
 */

interface Token {
  name: string; // without leading --
  value: string;
}

function parseTokens(css: string): Token[] {
  const tokens: Token[] = [];
  const re = /--([a-zA-Z0-9-]+)\s*:\s*([^;]+);/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css)) !== null) {
    tokens.push({ name: m[1], value: m[2].trim() });
  }
  return tokens;
}

// Theme-neutral prefixes the token vocabulary is allowed to use. Anything else
// (e.g. `ant`, a brand or color-literal prefix) fails the audit.
const ALLOWED_PREFIXES = [
  'color',
  'surface',
  'text',
  'font',
  'line',
  'letter',
  'spacing',
  'layout',
  'radius',
  'shadow',
  'icon',
];

describe('FRG-UI-002: design tokens defined once with neutral names', () => {
  const tokens = parseTokens(tokensCss);
  const byName = new Map(tokens.map((t) => [t.name, t.value]));

  it('FRG-UI-002 — defines accent, surface, and spacing tokens with the handoff palette', () => {
    expect(tokens.length).toBeGreaterThan(0);
    expect(byName.has('color-accent')).toBe(true);
    expect([...byName.keys()].some((n) => n.startsWith('surface-'))).toBe(true);
    expect([...byName.keys()].some((n) => n.startsWith('spacing-'))).toBe(true);

    // Owner's 2026-07-10 design-handoff surfaces.
    expect(byName.get('surface-page')).toBe('#202020');
    expect(byName.get('surface-chrome')).toBe('#262626');
    expect(byName.get('surface-sidebar')).toBe('#262626');
    expect(byName.get('surface-card')).toBe('#282828');
    expect(byName.get('surface-input')).toBe('#1c1c1c');
    expect(byName.get('layout-sidebar-width')).toBe('212px');
    expect(byName.get('layout-header-height')).toBe('60px');
  });

  it('FRG-UI-002 — accent family + status/progress hues match the handoff', () => {
    expect(byName.get('color-accent')?.toLowerCase()).toBe('#57b877');
    expect(byName.get('color-accent-light')?.toLowerCase()).toBe('#7fce9a');
    expect(byName.get('color-warning')?.toLowerCase()).toBe('#e5a54b');
    expect(byName.get('color-info')?.toLowerCase()).toBe('#5d9cec');
    expect(byName.get('color-progress-complete')?.toLowerCase()).toBe('#2f5d40');
    expect(byName.get('color-progress-incomplete')?.toLowerCase()).toBe('#4a2523');
    expect(byName.get('color-progress-fill')?.toLowerCase()).toBe('#57b877');
  });

  it('FRG-UI-002 — the publisher/format default accent stays pinned to the token accent', () => {
    // palettes.ts intentionally duplicates the brand green as its fallback
    // accent (it feeds inline styles, not CSS). This pin fails the build if the
    // two drift, so a token-layer accent change can never silently leave the
    // data-map default behind.
    expect(PUBLISHER_ACCENT_DEFAULT.toLowerCase()).toBe(
      byName.get('color-accent')?.toLowerCase(),
    );
  });

  it('FRG-UI-002 — token-name audit rejects brand-named tokens (no ant-/forager/brand naming)', () => {
    const names = tokens.map((t) => t.name);
    const brandNamed = names.filter((n) => /(^|-)(ant|forager|brand)(-|$)/i.test(n));
    expect(brandNamed).toEqual([]);

    const offenders = names.filter(
      (n) => !ALLOWED_PREFIXES.some((p) => n === p || n.startsWith(`${p}-`)),
    );
    expect(offenders).toEqual([]);
  });
});

describe('FRG-UI-002: the token layer is the single source of the palette', () => {
  // The distinctive handoff palette values (accent family, warm-neutral
  // surfaces, semantic status/progress hues, and the publisher/format map
  // colors). Every one of these MUST appear only in the token layer
  // (tokens.css) or the publisher/format data maps (palettes.ts) — never
  // hardcoded in a component.
  const PALETTE_HEXES = [
    '#202020', '#262626', '#282828', '#2b2b2b', '#1c1c1c',
    '#57b877', '#7fce9a', '#66c98a', '#31543f', '#0f1f0d',
    '#e5a54b', '#d99a5b', '#5d9cec', '#8ab6f0', '#2f5d40',
    '#4a2523', '#e6e6e6',
    // publisher/format map values (palettes.ts)
    '#3a2626', '#26303c', '#c0555a', '#5a86c0', '#6fb87a',
  ];

  const HERE = dirname(fileURLToPath(import.meta.url));
  const SRC_ROOT = join(HERE, '..');
  const ALLOWED_FILES = new Set(['tokens.css', 'palettes.ts']);

  function walk(dir: string): string[] {
    const out: string[] = [];
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        out.push(...walk(full));
      } else if (/\.(css|ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name)) {
        out.push(full);
      }
    }
    return out;
  }

  it('FRG-UI-002 — no component hardcodes a palette hex outside the token layer', () => {
    const offenders: string[] = [];
    for (const file of walk(SRC_ROOT)) {
      if (ALLOWED_FILES.has(file.split('/').pop() as string)) continue;
      const text = readFileSync(file, 'utf8').toLowerCase();
      for (const hex of PALETTE_HEXES) {
        if (text.includes(hex)) {
          offenders.push(`${file.replace(SRC_ROOT, 'src')} contains ${hex}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
