import { test, expect, type APIRequestContext } from '@playwright/test';
import { copyFileSync, mkdirSync, readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { newApiContext, until } from './helpers';

/**
 * The read-only reference-library boundary end-to-end (FRG-SER-021,
 * FRG-SER-022, FRG-IMP-028, FRG-UI-045).
 *
 * A SEPARATE spec, not part of the spine, for two reasons: it needs its own
 * roots and its own on-disk fixture tree, and a failure here must not cascade
 * into the spine's shared library the way one serial group's crash skips every
 * step after it.
 *
 * Named `y2-*` so it sorts AFTER `y-library-import.spec.ts` (one worker, file
 * order): that spec drives the Library Import screen against the default-
 * selected root, so this one registers its extra roots only once that journey
 * has finished. It stays BEFORE the `z*` specs that restart/recreate the app.
 *
 * Why this tier and not the unit suites: the boundary's whole claim is that no
 * byte under the read-only root is created, moved, rewritten or removed. Only a
 * run against real mounts can assert that against the actual filesystem, and
 * `/reference` is deliberately mounted WRITABLE (compose.yaml) so a leak would
 * really mutate the fixture tree instead of being stopped by the kernel.
 *
 * The fixture tree, seeded host-side through the `${FORAGERR_E2E_RUN}/reference`
 * bind mount (files are copies of the canonical cbz):
 *
 *   /reference/Umbral Signal (1994)/Umbral Signal 01 (1994).cbz
 *   /reference/Umbral Signal (1994)/Umbral Signal 02 (1994).cbz
 *
 * The zero-padding is the point: the harness pins `FORAGERR_RENAME_ENABLED=true`,
 * so the naming template WOULD rewrite `01` to `001` for a writable root. An
 * unchanged listing is therefore a real refusal, not a template no-op.
 */

const BASE_URL = process.env.FORAGERR_BASE_URL ?? 'http://127.0.0.1:8789';
const RUN_DIR = process.env.FORAGERR_E2E_RUN ?? '';
const REFERENCE_DIR = RUN_DIR ? path.join(RUN_DIR, 'reference') : '';
const CBZ_SOURCE = RUN_DIR ? path.join(RUN_DIR, 'data', 'saga-001.cbz') : '';

// Container-side paths of the two extra mounts (compose.yaml). `/reference` is
// writable in the container and registered read-only; `/unwritable` is mounted
// :ro, so it is the readable-but-unwritable case FRG-SER-021 exists for.
const REFERENCE_ROOT = '/reference';
const UNWRITABLE_ROOT = '/unwritable';

// Fixture volumes the mock ComicVine serves for this tier (fixtures/mock_server.py
// RO_ADD_* / RO_INDEX_*). One per creation path: a series is unique per cv
// volume id, so the add path and the index-in-place path cannot share one.
const ADD_VOLUME_ID = 62001;
const ADD_VOLUME_NAME = 'Meridian Drift';
const INDEX_VOLUME_ID = 62002;
const INDEX_DIR = 'Umbral Signal (1994)';
const INDEX_FILES = ['Umbral Signal 01 (1994).cbz', 'Umbral Signal 02 (1994).cbz'];

const COMIC_MIME = 'application/vnd.comicbook+zip';

let api: APIRequestContext;
// State threaded across this serial group.
let referenceRootId = 0;
let addSeriesId = 0;
let addIssueId = 0;
let indexSeriesId = 0;

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  api = await newApiContext(BASE_URL);
});

test.afterAll(async () => {
  await api.dispose();
});

/** One file's identity for the zero-write proof: a rename changes the name, a
 *  move changes the inode, an archive rewrite changes size and mtime. */
type FileState = { name: string; size: number; mtimeMs: number; ino: number };

function snapshot(dir: string): FileState[] {
  return readdirSync(dir)
    .sort()
    .map((name) => {
      const s = statSync(path.join(dir, name));
      return { name, size: s.size, mtimeMs: s.mtimeMs, ino: s.ino };
    });
}

/** The `errors[]` discriminator every read-only refusal carries
 *  (api.errors READ_ONLY_FIELD). Asserted structurally — never on message
 *  prose, which is free to change. */
async function expectReadOnlyRefusal(
  res: { status(): number; json(): Promise<any> },
  what: string,
) {
  expect(res.status(), `${what} is refused with the read-only conflict`).toBe(409);
  const body = await res.json();
  expect(
    (body.errors ?? []).map((e: any) => e.field),
    `${what} carries the read_only field discriminator`,
  ).toContain('read_only');
}

/** Register a root, tolerating the "already registered" 400 a serial-group
 *  retry produces, and return the row the API lists for that path. */
async function ensureRoot(
  containerPath: string,
  readOnly: boolean,
): Promise<any> {
  const res = await api.post('/api/v1/rootfolder', {
    data: { path: containerPath, read_only: readOnly },
  });
  if (!res.ok()) {
    expect(
      await res.text(),
      `registering ${containerPath} failed for a reason other than a re-run`,
    ).toContain('already registered');
  }
  const roots = await (await api.get('/api/v1/rootfolder')).json();
  const row = roots.find((r: any) => r.path === containerPath);
  expect(row, `${containerPath} is listed as a root folder`).toBeTruthy();
  return row;
}

/** Await a command's terminal state and return the record. */
async function settled(commandId: number): Promise<any> {
  return until(
    async () => {
      const res = await api.get(`/api/v1/command/${commandId}`);
      if (!res.ok()) return false;
      const body = await res.json();
      return body.finished_at !== null ? body : false;
    },
    { label: `command ${commandId} to finish`, timeoutMs: 90_000 },
  );
}

test('FRG-PROC-010 FRG-SER-021 FRG-UI-045: a readable-but-unwritable root registers read-only while an ordinary registration of it is refused', async ({
  page,
}, testInfo) => {
  test.skip(!RUN_DIR, 'no compose run dir provided (run via e2e/run.sh)');

  // The discriminated OR, proven on ONE path: the same directory is refused as
  // an ordinary root and accepted as a read-only one. Only on the first attempt
  // — a retry re-enters this step with the root already registered, so the
  // refusal below would name the duplicate instead of the unwritability and
  // would mask whichever later step actually flaked.
  if (testInfo.retry === 0) {
    const ordinary = await api.post('/api/v1/rootfolder', {
      data: { path: UNWRITABLE_ROOT },
    });
    expect(ordinary.status(), 'an ordinary root must still be writable').toBe(400);
    const body = await ordinary.json();
    expect((body.errors ?? []).map((e: any) => e.field)).toContain('path');
    // Prose, deliberately: it is the only thing distinguishing this rejection
    // from the duplicate/nesting rejections the same field carries.
    expect(body.message).toMatch(/writable/i);
  }

  const unwritable = await ensureRoot(UNWRITABLE_ROOT, true);
  expect(unwritable.read_only, 'the :ro mount registers read-only').toBe(true);

  const reference = await ensureRoot(REFERENCE_ROOT, true);
  expect(reference.read_only, 'the reference root reports its read-only state').toBe(
    true,
  );
  referenceRootId = reference.id;

  // The writable root the rest of the suite uses is untouched by all of this.
  const roots = await (await api.get('/api/v1/rootfolder')).json();
  expect(roots.find((r: any) => r.path === '/library').read_only).toBe(false);

  // The settings screen marks both read-only roots and only those.
  await page.goto('/settings/media-management');
  await expect(page.getByTestId(`root-folder-read-only-${reference.id}`)).toBeVisible();
  await expect(page.getByTestId(`root-folder-read-only-${unwritable.id}`)).toBeVisible();
  const writableId = roots.find((r: any) => r.path === '/library').id;
  await expect(page.getByTestId(`root-folder-${writableId}`)).toBeVisible();
  await expect(page.getByTestId(`root-folder-read-only-${writableId}`)).toHaveCount(0);
});

test('FRG-PROC-010 FRG-SER-022 FRG-UI-045: a series added on a read-only root is unmonitored with no search dispatched', async ({
  page,
}) => {
  test.skip(!RUN_DIR, 'no compose run dir provided (run via e2e/run.sh)');

  // The add form's read-only treatment: picking the read-only root replaces the
  // monitor strategy and search-on-add controls with an explanation, so the
  // operator is never offered acquisition options the backend will override.
  // Asserted without submitting — the add itself goes through the API below,
  // where the override can be proven against a request that ASKS for both.
  await page.goto('/add');
  await page.getByRole('searchbox', { name: 'Search ComicVine' }).fill(ADD_VOLUME_NAME);
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  const card = page.getByTestId(`candidate-${ADD_VOLUME_ID}`);
  await expect(card).toBeVisible();
  const selectBtn = card.getByRole('button', { name: `Select ${ADD_VOLUME_NAME}` });
  if (await selectBtn.isEnabled()) {
    await selectBtn.click();
    const panel = page.getByTestId('add-options-panel');
    await expect(panel).toBeVisible();
    // By value, not by label: the option text also carries the free-space
    // suffix, which is environment-dependent.
    await panel
      .getByRole('combobox', { name: 'Root folder' })
      .selectOption(String(referenceRootId));
    await expect(page.getByTestId('add-read-only-note')).toBeVisible();
    await expect(
      panel.getByRole('radiogroup', { name: 'Monitor strategy' }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole('checkbox', { name: 'Start search for missing issues' }),
    ).toHaveCount(0);
  }

  // The boundary itself: a request that explicitly asks to monitor everything
  // and to search on add still yields an unmonitored, unsearched series
  // (FRG-SER-022 — acquisition is off by construction, not by later refusal).
  const existing = await (await api.get('/api/v1/series?page=1&pageSize=200')).json();
  const already = existing.records.find((s: any) => s.cv_volume_id === ADD_VOLUME_ID);
  if (already) {
    addSeriesId = already.id;
  } else {
    const created = await api.post('/api/v1/series', {
      data: {
        cv_volume_id: ADD_VOLUME_ID,
        root_folder_id: referenceRootId,
        monitor_strategy: 'all',
        monitor_new_items: 'all',
        search_on_add: true,
      },
    });
    expect(created.status(), `add on a read-only root: ${await created.text()}`).toBe(
      201,
    );
    const body = await created.json();
    addSeriesId = body.id;
    expect(body.read_only, 'the created series reports read-only').toBe(true);
    expect(body.monitored, 'monitor_strategy=all is overridden to unmonitored').toBe(
      false,
    );
  }
  expect(addSeriesId).toBeGreaterThan(0);

  // Its refresh populates issues from ComicVine (a database write, not a root
  // write) and every one of them arrives unmonitored.
  const detail = await until(
    async () => {
      const res = await api.get(`/api/v1/series/${addSeriesId}`);
      if (!res.ok()) return false;
      const body = await res.json();
      return body.statistics?.issue_count >= 1 ? body : false;
    },
    { label: 'refresh to populate the read-only series', timeoutMs: 60_000 },
  );
  expect(detail.monitored).toBe(false);
  expect(detail.read_only).toBe(true);
  const issues = await (
    await api.get(`/api/v1/issues?seriesId=${addSeriesId}&pageSize=200`)
  ).json();
  expect(issues.records.length).toBeGreaterThan(0);
  for (const issue of issues.records) {
    expect(issue.monitored, `issue #${issue.issue_number} is unmonitored`).toBe(false);
  }
  addIssueId = issues.records[0].id;

  // And search_on_add=true dispatched nothing: no search command names it.
  const commands = await (await api.get('/api/v1/command?pageSize=200')).json();
  const searches = commands.records.filter(
    (c: any) =>
      ['series-search', 'issue-search'].includes(c.name) &&
      c.payload?.series_id === addSeriesId,
  );
  expect(searches, 'no search was dispatched for a read-only series').toHaveLength(0);
});

test('FRG-PROC-010 FRG-SER-022: search and monitoring for a read-only series are refused with the uniform 409, by route and by direct command', async () => {
  test.skip(!RUN_DIR, 'no compose run dir provided (run via e2e/run.sh)');

  // Interactive search — refused before any indexer budget is spent.
  await expectReadOnlyRefusal(
    await api.get(`/api/v1/release?issueId=${addIssueId}`),
    'interactive search',
  );

  // The monitored toggle, the other half of the acquisition surface.
  await expectReadOnlyRefusal(
    await api.put(`/api/v1/issues/${addIssueId}`, { data: { monitored: true } }),
    'the issue monitor toggle',
  );
  await expectReadOnlyRefusal(
    await api.put('/api/v1/issues/monitor', {
      data: { issue_ids: [addIssueId], monitored: true },
    }),
    'the bulk monitor toggle',
  );

  // The route is not the boundary (FRG-SER-021): enqueuing the search command
  // straight through the generic command transport reaches the same refusal in
  // the handler, so the command FAILS instead of reaching an indexer.
  const enqueued = await api.post('/api/v1/command', {
    data: { name: 'series-search', payload: { series_id: addSeriesId } },
  });
  expect(enqueued.status()).toBe(201);
  const record = await settled((await enqueued.json()).id);
  expect(record.status, 'a directly-enqueued search fails closed').toBe('failed');
  expect(record.error ?? '').toMatch(/read-only/i);
});

test('FRG-PROC-010 FRG-IMP-028: library import indexes a read-only root in place, renaming and moving nothing', async () => {
  test.skip(!RUN_DIR, 'no compose run dir provided (run via e2e/run.sh)');

  const seriesDir = path.join(REFERENCE_DIR, INDEX_DIR);
  const before = await (await api.get('/api/v1/series?page=1&pageSize=200')).json();
  const already = before.records.find((s: any) => s.cv_volume_id === INDEX_VOLUME_ID);

  let seeded: FileState[];
  if (already) {
    // Retry path: the import already ran, so only the end state can be checked.
    indexSeriesId = already.id;
    seeded = snapshot(seriesDir);
  } else {
    mkdirSync(seriesDir, { recursive: true });
    for (const name of INDEX_FILES) {
      copyFileSync(CBZ_SOURCE, path.join(seriesDir, name));
    }
    seeded = snapshot(seriesDir);
    expect(seeded.map((f) => f.name)).toEqual([...INDEX_FILES].sort());

    const scan = await api.post('/api/v1/library-import/scan', {
      data: { rootFolderId: referenceRootId },
    });
    expect(scan.status(), `scan the read-only root: ${await scan.text()}`).toBe(201);
    await settled((await scan.json()).id);

    const group = await until(
      async () => {
        const res = await api.get(
          `/api/v1/library-import?rootFolderId=${referenceRootId}&pageSize=200`,
        );
        if (!res.ok()) return false;
        const body = await res.json();
        return body.records.find((g: any) => g.folder.endsWith(INDEX_DIR)) ?? false;
      },
      { label: 'the read-only root to stage a group', timeoutMs: 60_000 },
    );
    expect(group.files, 'both existing files staged').toHaveLength(2);
    expect(group.proposedCvVolumeId).toBe(INDEX_VOLUME_ID);

    const confirmed = await api.patch(`/api/v1/library-import/groups/${group.id}`, {
      data: { state: 'confirmed' },
    });
    expect(confirmed.ok(), `confirm the group: ${await confirmed.text()}`).toBeTruthy();

    // Ask for monitoring and a search here too: the read-only root overrides
    // both, exactly as the add surface does.
    const execute = await api.post('/api/v1/library-import/execute', {
      data: {
        groupIds: [group.id],
        addOptions: { monitorStrategy: 'all', searchOnAdd: true },
      },
    });
    expect(execute.status(), `execute the import: ${await execute.text()}`).toBe(201);
    await settled((await execute.json()).id);
  }

  // The series is registered against the files where they already are.
  const series = await until(
    async () => {
      const list = await (await api.get('/api/v1/series?page=1&pageSize=200')).json();
      return list.records.find((s: any) => s.cv_volume_id === INDEX_VOLUME_ID) ?? false;
    },
    { label: 'the indexed read-only series to appear', timeoutMs: 60_000 },
  );
  indexSeriesId = series.id;
  expect(series.read_only).toBe(true);
  expect(series.monitored, 'an indexed read-only series is never monitored').toBe(false);
  expect(series.path).toBe(`${REFERENCE_ROOT}/${INDEX_DIR}`);

  const detail = await until(
    async () => {
      const res = await api.get(`/api/v1/series/${indexSeriesId}`);
      if (!res.ok()) return false;
      const body = await res.json();
      return body.statistics?.file_count === 2 ? body : false;
    },
    { label: 'both existing files to be attached', timeoutMs: 60_000 },
  );
  expect(detail.statistics.file_count).toBe(2);

  // The proof: nothing under the read-only root changed. Same names (no
  // rename, though the template would have renumbered `01` to `001`), same
  // inodes (no move or copy), same sizes and mtimes (no archive rewrite).
  expect(snapshot(seriesDir), 'the read-only root is byte-for-byte untouched').toEqual(
    seeded,
  );
  for (const name of INDEX_FILES) {
    expect(
      readFileSync(path.join(seriesDir, name)).equals(readFileSync(CBZ_SOURCE)),
      `${name} still holds the seeded bytes`,
    ).toBe(true);
  }

  // Both issues carry their existing file, and no download was involved.
  const issues = await (
    await api.get(`/api/v1/issues?seriesId=${indexSeriesId}&pageSize=200`)
  ).json();
  for (const num of ['1', '2']) {
    const issue = issues.records.find((i: any) => i.issue_number === num);
    expect(issue, `issue #${num} exists`).toBeTruthy();
    expect(issue.has_file, `issue #${num} points at its existing file`).toBe(true);
  }
  const queue = await (await api.get('/api/v1/queue')).json();
  expect(
    (queue.records ?? []).filter((q: any) => q.seriesId === indexSeriesId),
  ).toHaveLength(0);

  // OPDS serves the in-place file, byte-identical to what is on the mount.
  const acq = await api.get(`/opds/series/${indexSeriesId}`);
  expect(acq.status()).toBe(200);
  const acqText = await acq.text();
  expect(acqText).toContain(COMIC_MIME);
  const fileHref = acqText.match(/\/opds\/file\/\d+/)?.[0];
  expect(fileHref, 'an acquisition file link for the read-only series').toBeTruthy();
  const download = await api.get(fileHref!);
  expect(download.status()).toBe(200);
  expect(Buffer.from(await download.body()).equals(readFileSync(CBZ_SOURCE))).toBe(true);
});

test('FRG-PROC-010 FRG-SER-021: file-mutating operations are refused and the read-only root stays untouched', async () => {
  test.skip(!RUN_DIR, 'no compose run dir provided (run via e2e/run.sh)');

  const seriesDir = path.join(REFERENCE_DIR, INDEX_DIR);
  const before = snapshot(seriesDir);
  expect(before, 'the fixture files are present to be protected').toHaveLength(2);

  await expectReadOnlyRefusal(
    await api.post('/api/v1/rename', { data: { seriesId: indexSeriesId } }),
    'renaming library files',
  );
  await expectReadOnlyRefusal(
    await api.delete(`/api/v1/series/${indexSeriesId}?deleteFiles=true`),
    'delete-with-files',
  );

  // Again by the route that bypasses the endpoints: the rename command's own
  // handler refuses, so nothing is renamed even when the command is enqueued
  // directly (FRG-SER-021 — enforced in the flow, not only at the route).
  const enqueued = await api.post('/api/v1/command', {
    data: { name: 'rename-series', payload: { series_id: indexSeriesId } },
  });
  expect(enqueued.status()).toBe(201);
  const record = await settled((await enqueued.json()).id);
  expect(record.status, 'a directly-enqueued rename fails closed').toBe('failed');

  // The whole point of running this at this tier: the files are still exactly
  // as they were, and the series still owns them.
  expect(snapshot(seriesDir), 'no byte was renamed, moved or removed').toEqual(before);
  const detail = await (await api.get(`/api/v1/series/${indexSeriesId}`)).json();
  expect(detail.statistics.file_count).toBe(2);
});

test('FRG-PROC-010 FRG-UI-045: the UI marks a read-only series and offers none of the refused actions', async ({
  page,
}) => {
  test.skip(!RUN_DIR, 'no compose run dir provided (run via e2e/run.sh)');

  await page.goto(`/series/${indexSeriesId}`);
  await expect(page.getByTestId('series-read-only-badge')).toBeVisible();

  // The issue table renders (browsing is unaffected) but carries no per-issue
  // acquisition affordance.
  await expect(page.locator('[data-testid^="issue-row-"]').first()).toBeVisible();
  await expect(
    page.getByRole('button', { name: /Interactive search for issue/ }),
  ).toHaveCount(0);

  // No series-level search, no Edit (its only field is a monitoring policy).
  await expect(page.getByRole('button', { name: 'Search Monitored' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Search All' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Edit' })).toHaveCount(0);

  // Refresh stays — it writes to the database, not to the root.
  await expect(page.getByRole('button', { name: 'Refresh' })).toBeVisible();

  // No rename in the overflow menu; Rescan stays (a read-only rescan moves
  // nothing).
  await page.getByTestId('series-overflow-trigger').click();
  const menu = page.getByTestId('series-overflow-menu');
  await expect(menu.getByRole('menuitem', { name: 'Rescan' })).toBeVisible();
  await expect(menu.getByRole('menuitem', { name: 'Rename Files' })).toHaveCount(0);
  await page.keyboard.press('Escape');

  // Delete is still offered — the rows-only delete writes nothing to the root —
  // and the dialog says so instead of offering a delete-files option.
  await page.getByRole('button', { name: 'Delete' }).first().click();
  const dialog = page.getByRole('dialog', { name: /^Delete / });
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByText(/read-only library — files on disk are never touched/i),
  ).toBeVisible();
  await expect(
    dialog.getByRole('checkbox', { name: 'Also delete files from disk' }),
  ).toHaveCount(0);
  await page.keyboard.press('Escape');

  // And the library browse marks it, so the operator sees it before opening it.
  await page.goto('/');
  await expect(page.getByTestId(`series-read-only-${indexSeriesId}`)).toBeVisible();
});
