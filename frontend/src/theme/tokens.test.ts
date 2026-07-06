import { describe, it, expect } from 'vitest';
import tokensCss from './tokens.css?raw';

/**
 * FRG-UI-002 — token definitions parsed straight from tokens.css.
 * Covers: "tokens defined once with theme-neutral names" and
 * "token-name audit rejects brand-named tokens".
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
  'spacing',
  'layout',
  'radius',
  'shadow',
  'icon',
];

describe('FRG-UI-002: design tokens defined once with neutral names', () => {
  const tokens = parseTokens(tokensCss);
  const byName = new Map(tokens.map((t) => [t.name, t.value]));

  it('FRG-UI-002 — defines accent, surface, and spacing tokens with Sonarr-dark defaults', () => {
    expect(tokens.length).toBeGreaterThan(0);
    expect(byName.has('color-accent')).toBe(true);
    expect([...byName.keys()].some((n) => n.startsWith('surface-'))).toBe(true);
    expect([...byName.keys()].some((n) => n.startsWith('spacing-'))).toBe(true);

    // Sonarr-dark measured defaults.
    expect(byName.get('surface-page')).toBe('#202020');
    expect(byName.get('surface-chrome')).toBe('#2a2a2a');
    expect(byName.get('layout-sidebar-width')).toBe('210px');
  });

  it('FRG-UI-002 — accent token resolves to the ant brand color value', () => {
    expect(byName.get('color-accent')?.toLowerCase()).toBe('#57b877');
  });

  it('FRG-UI-002 — token-name audit rejects brand-named tokens (no ant-/brand naming)', () => {
    const names = tokens.map((t) => t.name);
    // Explicitly reject an `ant`/brand segment anywhere in a token name.
    const brandNamed = names.filter((n) => /(^|-)(ant|forager|brand)(-|$)/i.test(n));
    expect(brandNamed).toEqual([]);

    // Positively enforce the neutral vocabulary: every token starts with an
    // approved, theme-neutral prefix.
    const offenders = names.filter(
      (n) => !ALLOWED_PREFIXES.some((p) => n === p || n.startsWith(`${p}-`)),
    );
    expect(offenders).toEqual([]);
  });
});
