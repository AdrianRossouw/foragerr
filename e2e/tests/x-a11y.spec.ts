import { test, expect, type Page } from '@playwright/test';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

/**
 * Accessibility tier (FRG-PROC-019 / FRG-UI-038). An axe-core WCAG 2.1 A/AA scan
 * of the authenticated core screens that fails the suite on ANY serious- or
 * critical-impact violation — zero-tolerance, no baseline file, because the four
 * m9-a11y-fixes findings land in the same change so the clean state is the
 * starting invariant.
 *
 * File name `x-a11y` sorts AFTER `spine.spec.ts` and
 * `w-calendar-legibility.spec.ts` (single worker, file order), so the library
 * already holds the series/issue the spine grabs and imports and the Calendar's
 * seeded dense week — the scanned screens render real content in both
 * presentations, not just empty states.
 *
 * axe-core is e2e dev tooling injected at runtime from the resolved package
 * source (SOUP-register-exempt per the harness's existing note, like
 * Playwright). It is injected via `page.evaluate(<source>)` — CDP Runtime
 * evaluation, which is not subject to the page CSP — rather than a
 * script tag, so a strict app CSP cannot block the scan.
 */

const require = createRequire(import.meta.url);
const AXE_SOURCE = readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');

// The WCAG tag families the scan enforces (mirrors the owner-directed
// post-cycle scan: WCAG 2.1 A/AA).
const WCAG_TAGS = ['wcag2a', 'wcag21a', 'wcag2aa', 'wcag21aa'] as const;

// The authenticated core screens. Kept in one place so the coverage set is
// obvious; every route is inside AuthGate and reached with the saved session.
const CORE_ROUTES = [
  '/',
  '/add',
  '/calendar',
  '/wanted',
  '/queue',
  '/history',
  '/settings/general',
  '/settings/indexers',
  '/settings/download-clients',
  '/settings/media-management',
  '/settings/security',
  '/sources',
  '/system/health',
  '/system/logs',
] as const;

interface AxeNode {
  target: string[];
}
interface AxeViolation {
  id: string;
  impact: string | null;
  help: string;
  nodes: AxeNode[];
}
interface AxeResults {
  violations: AxeViolation[];
}

/** A serious/critical violation, flattened to the one line the failure needs. */
interface Finding {
  route: string;
  rule: string;
  impact: string;
  help: string;
  target: string;
}

/**
 * Both sides of the compact crossover (FRG-UI-049). Below it the shell unmounts
 * the sidebar for an off-canvas drawer and screens switch presentation, so a
 * wide-only scan leaves the compact chrome, the Calendar's cards and its action
 * rail unchecked by any automated ruleset.
 */
const VIEWPORTS = [
  { label: 'wide', width: 1280, height: 900 },
  { label: 'compact', width: 600, height: 900 },
] as const;

async function scanRoute(
  page: Page,
  route: string,
  compact: boolean,
): Promise<Finding[]> {
  await page.goto(route);
  // The app shell only mounts inside the authenticated tree; the "shell is
  // really up" signal differs by width, because the sidebar footer status row is
  // one of the things compact mode does not render — gating on it is what kept
  // this scan from being pointed at compact mode at all.
  // We deliberately do NOT waitForLoadState('networkidle') — the app holds a
  // live WebSocket open, so the network never goes idle.
  await expect(
    page.getByTestId(compact ? 'nav-toggle' : 'sidebar-status'),
  ).toBeVisible();
  // Let per-screen content paint so contrast/structure is scanned as the user
  // sees it, not a transient loading frame.
  // Settle: fixed waits alone can scan a loading frame (false pass). Give
  // the screen a beat, then require any visible loading placeholder to clear.
  await page.waitForTimeout(750);
  await expect
    .poll(async () => page.getByText(/^Loading\b/i).count(), { timeout: 10_000 })
    .toBe(0);

  // Inject axe as a page-context expression (CDP eval; CSP-exempt), then run it.
  await page.evaluate(AXE_SOURCE);
  const results = (await page.evaluate(
    async (tags) =>
      // @ts-expect-error injected at runtime on window
      await window.axe.run(document, { runOnly: { type: 'tag', values: tags } }),
    WCAG_TAGS as unknown as string[],
  )) as AxeResults;

  return results.violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .flatMap((v) =>
      v.nodes.map((n) => ({
        route,
        rule: v.id,
        impact: v.impact ?? 'unknown',
        help: v.help,
        target: n.target.join(' '),
      })),
    );
}

test('FRG-PROC-019 FRG-UI-038 FRG-UI-049: core screens carry zero serious/critical axe WCAG 2.1 A/AA violations at both viewports', async ({
  page,
}) => {
  const findings: Finding[] = [];
  for (const viewport of VIEWPORTS) {
    const compact = viewport.label === 'compact';
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const route of CORE_ROUTES) {
      findings.push(
        ...(await scanRoute(page, route, compact)).map((f) => ({
          ...f,
          route: `${f.route} @${viewport.label}`,
        })),
      );
    }
  }

  // On failure the message names every offending screen, rule id, and the first
  // node selector so a regression is diagnosable straight from the run log.
  const message =
    findings.length === 0
      ? ''
      : 'Serious/critical accessibility violations:\n' +
        findings
          .map(
            (f) =>
              `  [${f.route}] ${f.rule} (${f.impact}) — ${f.help} @ ${f.target}`,
          )
          .join('\n');
  expect(findings, message).toEqual([]);
});
