import { describe, it, expect } from 'vitest';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

/*
 * FRG-UI-009 — renderer-reuse AUDIT.
 *
 * The download-client settings screen must be the SAME generic schema-form
 * renderer as indexers with zero new form code. This test enforces that
 * structurally, on the real module graph:
 *
 *   1. Any module reachable from EITHER settings screen that renders form
 *      elements (<input>/<select>/<textarea>/<form>/<option>) must live in
 *      the shared renderer directory `components/schemaForm/`.
 *   2. The set of form-rendering modules reachable from the download-client
 *      screen is a SUBSET of those reachable from the indexer screen — i.e.
 *      download clients introduce no form-rendering module of their own.
 *   3. The download-client screen file and the kind-config module contain no
 *      form-element JSX at all.
 *
 * If someone adds a bespoke download-client form (or any form code outside
 * the renderer), this test fails the build.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, '..', '..');

const FORM_JSX = /<(input|select|textarea|form|option)\b/;
const IMPORT_RE = /(?:import|export)\s[^'"]*?from\s+['"](\.{1,2}\/[^'"]+)['"]|import\s+['"](\.{1,2}\/[^'"]+)['"]/g;

function resolveImport(fromFile: string, spec: string): string | null {
  if (spec.endsWith('.css') || spec.endsWith('.svg')) return null;
  const base = resolve(dirname(fromFile), spec);
  for (const candidate of [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    resolve(base, 'index.ts'),
    resolve(base, 'index.tsx'),
  ]) {
    if (
      existsSync(candidate) &&
      (candidate.endsWith('.ts') || candidate.endsWith('.tsx'))
    ) {
      return candidate;
    }
  }
  return null;
}

/** Every .ts/.tsx module transitively reachable from an entry file. */
function moduleGraph(entry: string): Set<string> {
  const seen = new Set<string>();
  const stack = [entry];
  while (stack.length > 0) {
    const file = stack.pop()!;
    if (seen.has(file)) continue;
    seen.add(file);
    const source = readFileSync(file, 'utf8');
    for (const match of source.matchAll(IMPORT_RE)) {
      const target = resolveImport(file, match[1] ?? match[2]);
      if (target && !seen.has(target)) stack.push(target);
    }
  }
  return seen;
}

function formRenderingModules(graph: Set<string>): string[] {
  return [...graph]
    .filter((file) => FORM_JSX.test(readFileSync(file, 'utf8')))
    .sort();
}

const rel = (file: string) => file.slice(SRC.length + 1).split(sep).join('/');

const indexerEntry = resolve(SRC, 'routes/settings/IndexerSettings.tsx');
const dlEntry = resolve(SRC, 'routes/settings/DownloadClientSettings.tsx');

describe('FRG-UI-009: download-client settings introduce zero form-rendering code', () => {
  it('FRG-UI-009 — every form-rendering module reachable from a settings screen lives in the shared renderer', () => {
    const offenders = [
      ...new Set([
        ...formRenderingModules(moduleGraph(indexerEntry)),
        ...formRenderingModules(moduleGraph(dlEntry)),
      ]),
    ]
      .map(rel)
      .filter((file) => !file.startsWith('components/schemaForm/'));

    expect(offenders, `form-element JSX outside components/schemaForm/: ${offenders.join(', ')}`).toEqual([]);
  });

  it('FRG-UI-009 — the download-client module graph adds NO form-rendering module beyond the indexer graph', () => {
    const indexerForms = formRenderingModules(moduleGraph(indexerEntry)).map(rel);
    const dlForms = formRenderingModules(moduleGraph(dlEntry)).map(rel);

    // Sanity: the shared renderer really is in both graphs.
    expect(indexerForms).toContain('components/schemaForm/SchemaForm.tsx');
    expect(dlForms).toContain('components/schemaForm/SchemaForm.tsx');

    const extras = dlForms.filter((file) => !indexerForms.includes(file));
    expect(extras, `download-client-only form modules: ${extras.join(', ')}`).toEqual([]);
  });

  it('FRG-UI-009 — the download-client screen and kind config contain no form-element JSX themselves', () => {
    for (const file of [
      dlEntry,
      resolve(SRC, 'components/settings/providerKinds.ts'),
    ]) {
      expect(
        FORM_JSX.test(readFileSync(file, 'utf8')),
        `${rel(file)} must not render form elements`,
      ).toBe(false);
    }
  });
});
