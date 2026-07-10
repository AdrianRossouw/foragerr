import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * FRG-UI-002 — Scenario: No external asset fetches. Fonts (Roboto) and icons
 * (Font Awesome 6 Free) are vendored from npm packages and bundled into the
 * SPA's own assets; the built app must never reach a font/icon CDN at runtime.
 *
 * This is a source-scan pin (the hermetic counterpart of a live network
 * assertion): no source file may reference a font/icon CDN host, and the
 * self-hosted packages must actually be imported.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = join(HERE, '..');

// Hosts a webfont/icon CDN would be fetched from. If any of these appears in a
// source file, an external request would occur at runtime.
const CDN_HOSTS = [
  'fonts.googleapis.com',
  'fonts.gstatic.com',
  'use.fontawesome.com',
  'kit.fontawesome.com',
  'ka-f.fontawesome.com',
  'cdnjs.cloudflare.com',
  'maxcdn.bootstrapcdn.com',
];

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (/\.(css|ts|tsx|html)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name))
      out.push(full);
  }
  return out;
}

describe('FRG-UI-002: fonts and icons are self-hosted (no CDN)', () => {
  it('FRG-UI-002 — no source file references a font/icon CDN host', () => {
    const offenders: string[] = [];
    for (const file of walk(SRC_ROOT)) {
      const text = readFileSync(file, 'utf8').toLowerCase();
      for (const host of CDN_HOSTS) {
        if (text.includes(host)) offenders.push(`${file} references ${host}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('FRG-UI-002 — the self-hosted Roboto + Font Awesome 6 packages are imported', () => {
    const main = readFileSync(join(SRC_ROOT, 'main.tsx'), 'utf8');
    expect(main).toContain('@fontsource/roboto');
    expect(main).toContain('@fortawesome/fontawesome-free');
    // Font Awesome pinned to the 6.x family the design specifies.
    const pkg = JSON.parse(readFileSync(join(SRC_ROOT, '..', 'package.json'), 'utf8'));
    expect(pkg.dependencies['@fortawesome/fontawesome-free']).toMatch(/\^?6/);
    expect(pkg.dependencies['@fontsource/roboto']).toBeTruthy();
  });
});
