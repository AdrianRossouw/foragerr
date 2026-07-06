import { test, expect, request as pwRequest } from '@playwright/test';
import {
  copyFileSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from 'node:fs';
import path from 'node:path';
import { until } from './helpers';

/**
 * Existing-library import flow (FRG-PROC-010, FRG-UI-015, FRG-IMP-022/023):
 * a pre-existing folder tree under the seeded /library root is scanned into
 * staged groups, reviewed (proposed ComicVine match vs an explicit no-match
 * state), confirmed, and bulk-imported IN PLACE — issues end up with files
 * without any download having run.
 *
 * Named `y-*` so it runs AFTER the spine (alphabetical, one worker) — the
 * scan must see the spine's imported Saga file as already-tracked and never
 * re-stage it — and BEFORE the zz-* specs that restart/recreate the app
 * container. Self-contained: it seeds its own folders through the host-side
 * `${FORAGERR_E2E_RUN}/library` bind mount (the same mechanism run.sh uses to
 * seed the canonical cbz) and drives everything else through the real UI.
 *
 * The fixture tree (files are copies of the canonical cbz — comfortably above
 * the importer's size floors, and filenames the parser groups per folder):
 *
 *   /library/Fables (2002)/Fables 001 (2002).cbz     <- matches mockhub 4977
 *   /library/Fables (2002)/Fables 002 (2002).cbz
 *   /library/Fables (2002)/._Fables 001 (2002).cbz   <- AppleDouble junk
 *   /library/Zenithal Chronicle (1987)/...001.cbz    <- no ComicVine result
 *
 * The AppleDouble sidecar pins the shared walk's junk predicates end-to-end
 * (FRG-IMP-022): the Fables group must stage exactly 2 files. (Zero-byte
 * files are deliberately NOT walk-skipped — they surface as visible
 * decision-time rejections; that path is pinned by backend unit tests.)
 */

const BASE_URL = process.env.FORAGERR_BASE_URL ?? 'http://127.0.0.1:8789';
const RUN_DIR = process.env.FORAGERR_E2E_RUN ?? '';
const LIBRARY_DIR = RUN_DIR ? path.join(RUN_DIR, 'library') : '';
const CBZ_SOURCE = RUN_DIR ? path.join(RUN_DIR, 'data', 'saga-001.cbz') : '';

// The library-import fixture volume mockhub serves (mock_server.py LI_*).
const LI_CV_VOLUME_ID = 4977;
const MATCH_DIR = 'Fables (2002)';
const MATCH_FILES = ['Fables 001 (2002).cbz', 'Fables 002 (2002).cbz'];
const NOMATCH_DIR = 'Zenithal Chronicle (1987)';
const NOMATCH_FILE = 'Zenithal Chronicle 001 (1987).cbz';

function seedFixtureTree(): void {
  const matchDir = path.join(LIBRARY_DIR, MATCH_DIR);
  mkdirSync(matchDir, { recursive: true });
  for (const name of MATCH_FILES) {
    copyFileSync(CBZ_SOURCE, path.join(matchDir, name));
  }
  // Junk the shared walk must skip (FRG-IMP-022): an AppleDouble sidecar.
  // It must not appear in the staged group's file list.
  writeFileSync(path.join(matchDir, `._${MATCH_FILES[0]}`), 'apple-double junk');

  const noMatchDir = path.join(LIBRARY_DIR, NOMATCH_DIR);
  mkdirSync(noMatchDir, { recursive: true });
  copyFileSync(CBZ_SOURCE, path.join(noMatchDir, NOMATCH_FILE));
}

test('FRG-PROC-010 FRG-UI-015 FRG-IMP-022 FRG-IMP-023: library import scans a root, reviews matches and imports existing files in place without a download', async ({ page }) => {
  test.skip(!RUN_DIR, 'no compose run dir provided (run via e2e/run.sh)');

  const api = await pwRequest.newContext({ baseURL: BASE_URL, ignoreHTTPSErrors: true });

  // Serial-retry guard (spine convention): if a previous attempt already
  // executed the import, the staged group is gone (its files are tracked), so
  // only the end-state verification below can re-run — not the UI journey.
  const before = await (await api.get('/api/v1/series?page=1&pageSize=200')).json();
  const alreadyImported = before.records.some(
    (s: any) => s.cv_volume_id === LI_CV_VOLUME_ID,
  );

  if (!alreadyImported) {
    seedFixtureTree();

    // The seeded root folder (/library) drives everything; no raw paths cross
    // the API (the scan takes a rootFolderId only).
    const roots = await (await api.get('/api/v1/rootfolder')).json();
    const root = roots.find((r: any) => r.path === '/library');
    expect(root, 'the seeded /library root folder').toBeTruthy();

    // Reach the screen the way a user does: the sidebar entry + route.
    await page.goto('/');
    await page.getByRole('link', { name: 'Library Import' }).click();
    await page.waitForURL(/\/library-import$/);

    // Explicit pre-scan empty state — never a blank results area. (Skipped on
    // a retry that had already scanned: staging is persisted server-side.)
    const staged = await (
      await api.get(`/api/v1/library-import?rootFolderId=${root.id}`)
    ).json();
    if (staged.totalRecords === 0) {
      await expect(page.getByTestId('li-empty-unscanned')).toBeVisible();
    }

    // Scan. The running state (command chip / disabled button) is transient —
    // the watched command can complete between expect polls — so accept either
    // the live status chip or the staged groups it resolves into.
    await page.getByTestId('li-scan').click();
    await expect(
      page
        .getByTestId('li-scan-status')
        .or(page.locator('[data-testid^="li-group-"]').first())
        .first(), // both can match on a retry with groups already staged
    ).toBeVisible();

    // Staged groups render once the scan command completes.
    const groupCards = page.locator('[data-testid^="li-group-"]');
    const fables = groupCards.filter({ hasText: MATCH_DIR });
    const zenithal = groupCards.filter({ hasText: NOMATCH_DIR });
    await expect(fables).toBeVisible({ timeout: 60_000 });
    await expect(zenithal).toBeVisible();

    // The Fables group: exactly the 2 real files (junk skipped, FRG-IMP-022),
    // a parse-confidence chip, and the proposed ComicVine match rendered with
    // name, year, publisher and poster (FRG-UI-015 scenario 1).
    await expect(fables.getByText('2 files')).toBeVisible();
    await expect(fables.getByText(/^Confidence \d+%$/)).toBeVisible();
    await expect(fables.getByText('Proposed', { exact: true })).toBeVisible();
    // Proposal details: name+year title, publisher, poster. The year span
    // alone is exactly "(2002)"; the poster's alt carries the proposed name
    // (the mockhub image host is not resolvable from the harness browser, so
    // assert presence, not pixel load).
    await expect(fables.getByText('(2002)', { exact: true })).toBeVisible();
    await expect(fables.getByText('Vertigo')).toBeVisible();
    await expect(fables.locator('img[alt="Fables cover"]')).toBeAttached();

    // The unknown series is an explicit no-match state, not selectable for
    // import until the user picks a volume (FRG-UI-015 scenario 2 gate).
    await expect(zenithal.getByText('No match', { exact: true })).toBeVisible();
    await expect(zenithal.locator('[data-testid^="li-no-match-"]')).toBeVisible();
    await expect(zenithal.getByRole('checkbox')).toBeDisabled();

    // Nothing has been imported by the scan itself (review-first, FRG-IMP-023).
    const mid = await (await api.get('/api/v1/series?page=1&pageSize=200')).json();
    expect(
      mid.records.some((s: any) => s.cv_volume_id === LI_CV_VOLUME_ID),
      'scan alone must not create a series',
    ).toBe(false);

    // Confirm the proposal, then import with the batch add options: the root
    // is fixed to the scanned one; format profile + monitor apply batch-wide.
    await fables.getByRole('button', { name: 'Confirm match' }).click();
    await expect(fables.getByText('Confirmed', { exact: true })).toBeVisible();

    const panel = page.getByTestId('li-batch-panel');
    await expect(panel).toBeVisible();
    await expect(page.getByTestId('li-batch-root')).toHaveText('/library');
    await panel.getByRole('combobox', { name: 'Format profile' }).selectOption({ index: 0 });
    await expect(page.getByTestId('li-import-confirm')).toHaveText('Import 1 selected');
    await page.getByTestId('li-import-confirm').click();

    // The per-group outcome lands on the card once the command completes.
    await expect(fables.getByText('Imported', { exact: true })).toBeVisible({
      timeout: 90_000,
    });
  }

  // --- end-state verification (also the retry path) --------------------------

  // The series exists with BOTH existing files attached — hasFile without any
  // download (FRG-UI-015 scenario 3 / FRG-IMP-023 in-place import).
  const series = await until(
    async () => {
      const list = await (await api.get('/api/v1/series?page=1&pageSize=200')).json();
      return list.records.find((s: any) => s.cv_volume_id === LI_CV_VOLUME_ID) ?? false;
    },
    { label: 'the library-imported series to appear', timeoutMs: 30_000 },
  );
  const detail = await (await api.get(`/api/v1/series/${series.id}`)).json();
  expect(detail.statistics.file_count).toBe(2);
  // In-place: the series is pinned to the scanned folder and the files never
  // leave it. Renaming is enabled by default, so each file is renamed to the
  // naming template WITHIN that folder — no cross-folder move, no repackaging
  // (byte-identical to what was seeded), and no download.
  expect(detail.path).toBe(`/library/${MATCH_DIR}`);
  const seriesDir = path.join(LIBRARY_DIR, MATCH_DIR);
  const renamed = readdirSync(seriesDir).filter((f) =>
    /^Fables 00[12] \(2002\) \[__\d+__\]\.cbz$/.test(f),
  );
  expect(renamed, 'both files renamed per the template in place').toHaveLength(2);
  for (const name of renamed) {
    expect(
      readFileSync(path.join(seriesDir, name)).equals(readFileSync(CBZ_SOURCE)),
      `${name} is byte-identical to the seeded file`,
    ).toBe(true);
  }

  const issues = await (
    await api.get(`/api/v1/issues?seriesId=${series.id}&pageSize=200`)
  ).json();
  for (const num of ['1', '2']) {
    const issue = issues.records.find((i: any) => i.issue_number === num);
    expect(issue, `issue #${num} exists`).toBeTruthy();
    expect(issue.has_file, `issue #${num} has its existing file`).toBe(true);
  }

  // No download was involved: the queue never tracked anything for this series.
  const queue = await (await api.get('/api/v1/queue')).json();
  expect(
    (queue.records ?? []).filter((q: any) => q.seriesId === series.id),
  ).toHaveLength(0);

  // And the series shows up in the library browse like any other.
  await page.goto('/');
  await expect(page.getByRole('link', { name: /Fables/ }).first()).toBeVisible();

  await api.dispose();
});
