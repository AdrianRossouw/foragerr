#!/usr/bin/env node
/**
 * Generate e2e/acceptance-report.md from the Playwright JSON reporter output
 * (FRG-PROC-010). There is NO hand-authored criteria matrix: every row is
 * derived from a real test — its title names the FRG requirement id(s) it
 * exercises, and its outcome (pass / fail / skipped) comes straight from the
 * run. Skipped-by-design tiers (the live-SAB tier) surface as "skipped".
 *
 * Usage: node acceptance-report.mjs <results.json> <out.md>
 */
import { readFileSync, writeFileSync } from 'node:fs';

const [, , inPath, outPath] = process.argv;
if (!inPath || !outPath) {
  console.error('usage: acceptance-report.mjs <results.json> <out.md>');
  process.exit(2);
}

const ID_RE = /FRG-[A-Z]{2,5}-\d{3}/g;

let report;
try {
  report = JSON.parse(readFileSync(inPath, 'utf8'));
} catch (err) {
  console.error(`could not read Playwright results at ${inPath}: ${err.message}`);
  process.exit(2);
}

/** Recursively collect every spec across nested suites. */
function collectSpecs(suite, file, acc) {
  const specFile = suite.file ?? file;
  for (const spec of suite.specs ?? []) {
    const statuses = (spec.tests ?? []).flatMap((t) =>
      (t.results ?? []).map((r) => r.status),
    );
    let outcome;
    if (spec.ok === false) outcome = 'fail';
    else if (statuses.length && statuses.every((s) => s === 'skipped')) outcome = 'skipped';
    else outcome = 'pass';
    const ids = [...new Set(spec.title.match(ID_RE) ?? [])].sort();
    acc.push({ title: spec.title, file: specFile, ids, outcome });
  }
  for (const child of suite.suites ?? []) collectSpecs(child, specFile, acc);
}

const specs = [];
for (const suite of report.suites ?? []) collectSpecs(suite, suite.file, specs);

const counts = { pass: 0, fail: 0, skipped: 0 };
for (const s of specs) counts[s.outcome]++;

const idToOutcomes = new Map();
for (const s of specs) {
  for (const id of s.ids) {
    if (!idToOutcomes.has(id)) idToOutcomes.set(id, new Set());
    idToOutcomes.get(id).add(s.outcome);
  }
}

const badge = { pass: 'PASS', fail: 'FAIL', skipped: 'SKIPPED' };
const hermeticFailed = counts.fail > 0;
const verdict = hermeticFailed ? 'RED' : 'GREEN';

const lines = [];
lines.push('# foragerr end-to-end acceptance report');
lines.push('');
lines.push(
  '_Generated from the Playwright JSON reporter by ' +
    '`e2e/scripts/acceptance-report.mjs` — do not edit by hand (FRG-PROC-010)._',
);
lines.push('');
lines.push(`- **Verdict:** ${verdict}`);
lines.push(
  `- **Scenarios:** ${specs.length} (` +
    `${counts.pass} pass, ${counts.fail} fail, ${counts.skipped} skipped)`,
);
if (report.stats?.startTime) {
  lines.push(`- **Run started:** ${report.stats.startTime}`);
}
lines.push('');
lines.push('## Scenario → requirement coverage');
lines.push('');
lines.push('| Result | Scenario | FRG requirement ids |');
lines.push('| --- | --- | --- |');
for (const s of specs) {
  const title = s.title.replace(/\|/g, '\\|');
  const ids = s.ids.length ? s.ids.join(', ') : '—';
  lines.push(`| ${badge[s.outcome]} | ${title} | ${ids} |`);
}
lines.push('');
lines.push('## Requirement roll-up');
lines.push('');
lines.push('| FRG id | Result |');
lines.push('| --- | --- |');
for (const id of [...idToOutcomes.keys()].sort()) {
  const outcomes = idToOutcomes.get(id);
  const roll = outcomes.has('fail')
    ? 'FAIL'
    : outcomes.has('pass')
      ? 'PASS'
      : 'SKIPPED';
  lines.push(`| ${id} | ${roll} |`);
}
lines.push('');
if (hermeticFailed) {
  lines.push('## Failed scenarios');
  lines.push('');
  for (const s of specs.filter((x) => x.outcome === 'fail')) {
    lines.push(`- **${s.title}** (${s.file})`);
  }
  lines.push('');
}

writeFileSync(outPath, lines.join('\n') + '\n');
console.log(
  `acceptance-report.md written: ${verdict} — ` +
    `${counts.pass} pass / ${counts.fail} fail / ${counts.skipped} skipped`,
);
