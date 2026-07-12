// design-sync support: generate frontend/dist/types/index.d.ts re-exporting
// every component module, so the converter's .d.ts extractor (which reads the
// package's `types` entry) sees the real prop contracts instead of emitting
// `[key: string]: unknown` stubs. Run after `tsc -p .design-sync/tsconfig.dts.json`
// (both wired together as cfg.buildCmd — re-syncs run it before the converter).
import { readdirSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const typesRoot = join(here, '..', 'frontend', 'dist', 'types');
const compDir = join(typesRoot, 'components');
if (!existsSync(compDir)) {
  console.error('gen-types-barrel: no dist/types/components — run tsc -p .design-sync/tsconfig.dts.json first');
  process.exit(1);
}

const lines = [];
const walk = (dir, rel) => {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.isDirectory()) walk(join(dir, e.name), `${rel}/${e.name}`);
    else if (e.name.endsWith('.d.ts')) lines.push(`export * from './${rel}/${e.name.slice(0, -5)}';`.replace('.//', './'));
  }
};
walk(compDir, 'components');
writeFileSync(join(typesRoot, 'index.d.ts'), lines.sort().join('\n') + '\n');
console.log(`gen-types-barrel: ${lines.length} module re-exports → dist/types/index.d.ts`);
