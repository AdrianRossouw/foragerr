import { describe, it, expect } from 'vitest';
import {
  PUBLISHER_ACCENT,
  PUBLISHER_ACCENT_DEFAULT,
  PUBLISHER_TINT,
  PUBLISHER_TINT_DEFAULT,
  publisherAccent,
  publisherKey,
  publisherTint,
} from './palettes';

/**
 * FRG-UI-042 — publisher tint/accent resolution against the names feeds
 * actually deliver. The palette is keyed by imprint ("Marvel", "DC"); every
 * live entry arrives as a corporate name ("Marvel Comics", "BOOM! Studios"),
 * so an exact-match lookup resolved nothing on real data and every publisher
 * rendered in the brand accent.
 */

/** The hue a derived color must stay clear of: the brand accent's own. */
const BRAND_HUE = 140;
const BRAND_HUE_GUARD = 35;

function hueOf(color: string): number {
  const match = /^hsl\((\d+(?:\.\d+)?) /.exec(color);
  expect(match, `expected an hsl() color, got ${color}`).not.toBeNull();
  return Number((match as RegExpExecArray)[1]);
}

/** The hue of a `#rrggbb` literal, by the same HSL conversion the browser
 * uses — needed because `PUBLISHER_ACCENT_DEFAULT` is stored as a hex
 * literal, not an `hsl()` string like a derived color. */
function hexHue(hex: string): number {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  expect(match, `expected a #rrggbb color, got ${hex}`).not.toBeNull();
  const [r, g, b] = (match as RegExpExecArray).slice(1, 4).map((c) => parseInt(c, 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  if (delta === 0) return 0;
  let hue: number;
  if (max === r) hue = ((g - b) / delta) % 6;
  else if (max === g) hue = (b - r) / delta + 2;
  else hue = (r - g) / delta + 4;
  hue *= 60;
  return hue < 0 ? hue + 360 : hue;
}

describe('FRG-UI-042: live publisher names resolve to their palette colors', () => {
  const liveNames: [string, string][] = [
    ['Marvel Comics', 'Marvel'],
    ['DC Comics', 'DC'],
    ['BOOM! Studios', 'BOOM!'],
    ['Dark Horse Comics', 'Dark Horse'],
    ['Image Comics', 'Image'],
    ['IDW Publishing', 'IDW'],
  ];

  for (const [live, key] of liveNames) {
    it(`FRG-UI-042 — "${live}" resolves to the ${key} palette entry`, () => {
      expect(publisherAccent(live)).toBe(PUBLISHER_ACCENT[key]);
      expect(publisherTint(live)).toBe(PUBLISHER_TINT[key]);
      expect(publisherKey(live)).toBe(key);
    });
  }

  it('FRG-UI-042 — the bare palette keys still resolve to themselves', () => {
    // The fold is additive: names that already matched must not start missing.
    for (const key of Object.keys(PUBLISHER_ACCENT)) {
      expect(publisherAccent(key)).toBe(PUBLISHER_ACCENT[key]);
      expect(publisherKey(key)).toBe(key);
    }
  });

  it('FRG-UI-042 — the match is case-insensitive and tolerates surrounding space', () => {
    expect(publisherAccent('  marvel comics ')).toBe(PUBLISHER_ACCENT.Marvel);
    expect(publisherAccent('boom! STUDIOS')).toBe(PUBLISHER_ACCENT['BOOM!']);
    // The canonical casing is what the chip prints, not the feed's.
    expect(publisherKey('dc comics')).toBe('DC');
  });
});

describe('FRG-UI-042: BRAND_HUE tracks the real brand accent', () => {
  it("FRG-UI-042 — BRAND_HUE is PUBLISHER_ACCENT_DEFAULT's own hue", () => {
    // BRAND_HUE is a hand-derived literal (module comment: #57b877 ≈
    // 139.79°), not computed from the accent at runtime — so a future accent
    // change with no matching BRAND_HUE update would silently mis-center the
    // whole derived-hue guard band around a color the app no longer uses.
    const distance = Math.abs(hexHue(PUBLISHER_ACCENT_DEFAULT) - BRAND_HUE);
    expect(distance).toBeLessThan(2);
  });
});

describe('FRG-UI-042: a publisher outside the named palette gets a stable derived hue', () => {
  it('FRG-UI-042 — an unnamed publisher is not drawn in the brand accent', () => {
    const accent = publisherAccent('Titan Comics');
    expect(accent).not.toBe(PUBLISHER_ACCENT_DEFAULT);
    expect(publisherTint('Titan Comics')).not.toBe(PUBLISHER_TINT_DEFAULT);
  });

  it('FRG-UI-042 — the derived hue is stable across calls', () => {
    // Same publisher, same color on every surface and every reload: the hash
    // may depend on nothing but the normalized name.
    const first = publisherAccent('Titan Comics');
    expect(publisherAccent('Titan Comics')).toBe(first);
    expect(publisherAccent('titan')).toBe(first);
  });

  it('FRG-UI-042 — derived hues stay clear of the brand accent hue', () => {
    for (const name of [
      'Titan',
      'Oni Press',
      'Vault',
      'Mad Cave Studios',
      'Ablaze',
      'Fantagraphics',
      'Umbral Press',
      // Hashed 15° off brand under the old 15° guard — technically outside
      // it, but perceptually still near-green at this surface's saturation
      // and lightness. The 35° guard this probes hashes it to a different,
      // clearly-distinct hue.
      'Heavy Metal',
    ]) {
      const hue = hueOf(publisherAccent(name));
      const distance = Math.min(
        Math.abs(hue - BRAND_HUE),
        360 - Math.abs(hue - BRAND_HUE),
      );
      expect(distance).toBeGreaterThanOrEqual(BRAND_HUE_GUARD);
    }
  });

  it('FRG-UI-042 — two different unnamed publishers do not share one hue', () => {
    expect(publisherAccent('Titan')).not.toBe(publisherAccent('Vault'));
  });

  it('FRG-UI-042 — an unnamed publisher tint and accent share one hue', () => {
    // The pair is one identity at two weights; a spine whose edge and wash
    // disagreed would read as two publishers.
    expect(hueOf(publisherTint('Vault'))).toBe(hueOf(publisherAccent('Vault')));
  });
});

describe('FRG-UI-042: suffix folding is conservative', () => {
  it('FRG-UI-042 — "Press" is identity-bearing and is never folded away', () => {
    expect(publisherKey('Oni Press')).toBe('Oni Press');
    expect(publisherKey('Kobold Press')).toBe('Kobold Press');
    expect(publisherAccent('Oni Press')).not.toBe(publisherAccent('Oni'));
  });

  it('FRG-UI-042 — only trailing suffix words fold', () => {
    // A suffix word that is not in trailing position carries identity; folding
    // it would rewrite the publisher into one that does not exist.
    expect(publisherKey('Comics Experience')).toBe('Comics Experience');
  });

  it('FRG-UI-042 — a name made only of suffix words keeps itself', () => {
    expect(publisherKey('Comics')).toBe('Comics');
  });

  it('FRG-UI-042 — stacked suffixes fold down to the imprint', () => {
    expect(publisherKey('Marvel Comics Publishing')).toBe('Marvel');
  });
});

describe('FRG-UI-042: an absent publisher keeps the neutral defaults', () => {
  for (const absent of [null, undefined, '', '   ']) {
    it(`FRG-UI-042 — ${JSON.stringify(absent)} resolves to the default tint and accent`, () => {
      expect(publisherTint(absent)).toBe(PUBLISHER_TINT_DEFAULT);
      expect(publisherAccent(absent)).toBe(PUBLISHER_ACCENT_DEFAULT);
      expect(publisherKey(absent)).toBeNull();
    });
  }
});
