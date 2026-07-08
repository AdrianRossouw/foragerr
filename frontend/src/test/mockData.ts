import type {
  ApiPage,
  BlocklistRecord,
  CommandResource,
  FormatProfileResource,
  HealthWarningItem,
  HistoryRecord,
  IssueResource,
  LibraryImportGroup,
  LookupCandidate,
  ManualImportEntry,
  MediaManagementConfig,
  QueuePageResponse,
  QueueResourceRaw,
  ReleaseDecision,
  RootFolderResource,
  ScheduledTaskResource,
  Series,
  SeriesCreatedResource,
  SeriesDetail,
  SeriesGroupMember,
  SeriesGroupResource,
  SeriesResource,
  SeriesStatisticsResource,
  SuggestCandidate,
  SystemHealthComponent,
  SystemStatusResource,
  WantedIssueRecord,
} from '../api/types';

/** Typed MOCK data used to drive the fake fetcher. No live backend is contacted. */

export const mockSeriesList: Series[] = [
  { id: 1, title: 'Saga', monitored: true, haveCount: 40, totalCount: 63 },
  { id: 2, title: 'Bone', monitored: false, haveCount: 55, totalCount: 55 },
];

export const mockSeriesDetail: SeriesDetail = {
  id: 7,
  title: 'Invincible',
  monitored: true,
  haveCount: 100,
  totalCount: 144,
  publisher: 'Image',
  year: 2003,
  overview: 'A teenage superhero.',
  issues: [
    { id: 71, issueNumber: '1', monitored: true, hasFile: true },
    { id: 72, issueNumber: '1.5', monitored: true, hasFile: false },
  ],
};

/** Builds a raw queue record with sensible defaults; override per test. */
export function mockQueueRecord(
  overrides: Partial<QueueResourceRaw> & Pick<QueueResourceRaw, 'id'>,
): QueueResourceRaw {
  return {
    seriesId: 1,
    issueId: 410,
    series: { id: 1, title: 'Saga' },
    issue: { id: 410, issueNumber: '41', title: null },
    size: 100,
    sizeleft: 0,
    status: 'ok',
    state: 'downloading',
    statusMessages: [],
    downloadId: `SABnzbd_nzo_${overrides.id}`,
    protocol: 'usenet',
    downloadClient: 'sab',
    indexer: 'DogNZB',
    outputPath: null,
    estimatedCompletion: null,
    ...overrides,
  };
}

/** Wraps records in the backend's queue paging envelope (FRG-API-002 shape). */
export function mockQueueEnvelope(records: QueueResourceRaw[]): QueuePageResponse {
  return {
    page: 1,
    pageSize: 20,
    sortKey: 'added_at',
    sortDirection: 'desc',
    totalRecords: records.length,
    records,
  };
}

export const mockQueuePage1: QueuePageResponse = mockQueueEnvelope([
  mockQueueRecord({
    id: 900,
    issueId: 411,
    issue: { id: 411, issueNumber: '41', title: 'Chapter Forty-One' },
    size: 100,
    sizeleft: 90,
  }),
  mockQueueRecord({
    id: 901,
    issueId: 412,
    issue: { id: 412, issueNumber: '42', title: 'Chapter Forty-Two' },
    size: 100,
    sizeleft: 75,
  }),
]);

/**
 * Release decisions exactly as `/api/v1/release` serializes them, in comparator
 * order (approved best-first) — the UI must render them in THIS order.
 */
export const mockReleases: ReleaseDecision[] = [
  {
    indexer_id: 3,
    guid: 'guid-approved-best',
    indexer_name: 'DogNZB',
    title: 'Saga 041 (2017) (Digital)',
    format: 'cbz',
    size_bytes: 42_000_000,
    age_seconds: 3 * 86_400,
    score: 120,
    outcome: 'approved',
    approved: true,
    rejections: [],
  },
  {
    indexer_id: 4,
    guid: 'guid-approved-second',
    indexer_name: 'NZB.su',
    title: 'Saga 041 (2017) (Webrip)',
    format: 'cbr',
    size_bytes: 38_000_000,
    age_seconds: 40 * 86_400,
    score: 80,
    outcome: 'approved',
    approved: true,
    rejections: [],
  },
  {
    indexer_id: 4,
    guid: 'guid-rejected',
    indexer_name: 'NZB.su',
    title: 'Saga 041 scanned',
    format: null,
    size_bytes: 12_000_000,
    age_seconds: 900 * 86_400,
    score: -5,
    outcome: 'rejected',
    approved: false,
    rejections: ['Below minimum size', 'Release too old'],
  },
];

/*
 * ---------------------------------------------------------------------------
 * Backend-true mocks (snake_case resources mirroring the changes 3-5 API),
 * used by the library-cluster screens (FRG-UI-003..005).
 * ---------------------------------------------------------------------------
 */

export function makeStats(
  overrides: Partial<SeriesStatisticsResource> = {},
): SeriesStatisticsResource {
  return {
    issue_count: 10,
    file_count: 10,
    missing_count: 0,
    size_on_disk: 400_000_000,
    next_release_date: null,
    last_release_date: '2024-05-01',
    ...overrides,
  };
}

export function makeSeriesResource(
  overrides: Partial<SeriesResource> = {},
): SeriesResource {
  const id = overrides.id ?? 1;
  return {
    id,
    cv_volume_id: 4050_0000 + id,
    title: `Series ${id}`,
    sort_title: `series ${id}`,
    publisher: 'Image',
    start_year: 2010,
    status: 'continuing',
    monitored: true,
    monitor_new_items: 'all',
    format_profile_id: 1,
    root_folder_id: 1,
    path: `/comics/Series ${id}`,
    cover_cached_at: '2026-07-01T00:00:00Z',
    added_at: '2026-06-01T00:00:00Z',
    refreshed_at: '2026-07-01T00:00:00Z',
    description_sanitized: 'A mock series.',
    aliases: [],
    series_group_id: null,
    booktype: null,
    statistics: makeStats(),
    ...overrides,
  };
}

/** A 55-series library (FRG-UI-003 "50+ series" poster-grid scenario). */
export function makeMockLibrary(count = 55): SeriesResource[] {
  return Array.from({ length: count }, (_, i) => {
    const id = i + 1;
    const title = `${String.fromCharCode(65 + (i % 26))}${i} Chronicles`;
    return makeSeriesResource({
      id,
      title,
      sort_title: title.toLowerCase(),
      monitored: i % 3 !== 0,
      added_at: `2026-01-${String((i % 28) + 1).padStart(2, '0')}T00:00:00Z`,
      statistics: makeStats({
        issue_count: 20,
        file_count: i % 4 === 0 ? 12 : 20,
        missing_count: i % 4 === 0 ? 8 : 0,
      }),
    });
  });
}

/** A franchise-group member (the lean subset GET /series/groups serializes). */
export function makeGroupMember(
  overrides: Partial<SeriesGroupMember> & Pick<SeriesGroupMember, 'id'>,
): SeriesGroupMember {
  const id = overrides.id;
  return {
    cv_volume_id: 4050_0000 + id,
    title: `Series ${id}`,
    sort_title: `series ${id}`,
    status: 'continuing',
    start_year: 2010,
    monitored: true,
    series_group_id: null,
    ...overrides,
  };
}

/**
 * One GET /api/v1/series/groups record. Roll-up counts default to sensible
 * sums but are override-able so a test can pin an exact header stat.
 */
export function makeSeriesGroup(
  overrides: Partial<SeriesGroupResource> &
    Pick<SeriesGroupResource, 'title' | 'series'>,
): SeriesGroupResource {
  const members = overrides.series;
  return {
    id: overrides.kind === 'series' ? null : 1,
    kind: members.length > 1 ? 'group' : 'series',
    series_count: members.length,
    issue_count: members.length * 20,
    owned_count: members.length * 12,
    ...overrides,
  };
}

export function pageOf<T>(records: T[], overrides: Partial<ApiPage<T>> = {}): ApiPage<T> {
  return {
    page: 1,
    pageSize: 200,
    sortKey: 'sort_title',
    sortDirection: 'asc',
    totalRecords: records.length,
    records,
    ...overrides,
  };
}

export const mockSeriesResource: SeriesResource = makeSeriesResource({
  id: 7,
  title: 'Invincible',
  sort_title: 'invincible',
  publisher: 'Image',
  start_year: 2003,
  path: '/comics/Invincible (2003)',
  description_sanitized: 'Mark Grayson is a normal teenager, mostly.',
  statistics: makeStats({
    issue_count: 4,
    file_count: 2,
    missing_count: 2,
    size_on_disk: 120_000_000,
  }),
});

export function makeIssue(overrides: Partial<IssueResource> = {}): IssueResource {
  const id = overrides.id ?? 71;
  return {
    id,
    series_id: 7,
    cv_issue_id: 6000 + id,
    issue_number: '1',
    title: 'Family Matters',
    cover_date: '2003-01-01',
    store_date: null,
    issue_type: 'issue',
    monitored: true,
    added_at: '2026-06-01T00:00:00Z',
    has_file: false,
    file: null,
    ...overrides,
  };
}

/** Issue set covering the FRG-UI-004 string-number scenario ("1.5"/"1.MU"). */
export const mockIssues: IssueResource[] = [
  makeIssue({
    id: 71,
    issue_number: '1',
    title: 'Family Matters',
    has_file: true,
    file: { id: 501, path: '/comics/Invincible (2003)/Invincible 001.cbz', size: 52_428_800 },
  }),
  makeIssue({ id: 72, issue_number: '1.5', title: 'Interlude', cover_date: '2003-02-01' }),
  makeIssue({ id: 73, issue_number: '1.MU', title: 'Marvel Universe??', cover_date: '2003-03-01' }),
  makeIssue({
    id: 74,
    issue_number: '2',
    title: 'Second Chances',
    cover_date: '2003-04-01',
    monitored: false,
    has_file: true,
    file: { id: 502, path: '/comics/Invincible (2003)/Invincible 002.cbr', size: 41_943_040 },
  }),
];

export const mockLookupCandidates: LookupCandidate[] = [
  {
    cv_volume_id: 40501234,
    name: 'Saga',
    publisher: 'Image',
    start_year: 2012,
    image_url: 'https://comicvine.gamespot.com/a/uploads/scale_small/saga.jpg',
    count_of_issues: 63,
    name_similarity: 1.0,
    year_proximity: 0,
    target_issue_plausible: true,
    have_it: false,
  },
  {
    cv_volume_id: 40509999,
    name: 'Saga of the Swamp Thing',
    publisher: 'DC Comics',
    start_year: 1982,
    image_url: 'https://comicvine.gamespot.com/a/uploads/scale_small/swamp.jpg',
    // ComicVine did not report a count — the annotation is omitted, not "0".
    count_of_issues: null,
    name_similarity: 0.42,
    year_proximity: 30,
    target_issue_plausible: false,
    have_it: true,
  },
];

/**
 * ComicVine SUGGEST candidates (FRG-API-017) — the bounded, no-plausibility
 * shape the Add Series autosuggest dropdown renders (FRG-UI-005).
 */
export const mockSuggestCandidates: SuggestCandidate[] = [
  {
    cv_volume_id: 40501234,
    name: 'Saga',
    publisher: 'Image',
    start_year: 2012,
    image_url: 'https://comicvine.gamespot.com/a/uploads/scale_small/saga.jpg',
    count_of_issues: 63,
    have_it: false,
  },
];

/** `GET /api/v1/rootfolder` rows; null free_space = unreadable path. */
export const mockRootFolders: RootFolderResource[] = [
  { id: 1, path: '/comics', free_space: 250_000_000_000 },
  { id: 2, path: '/mnt/archive/comics', free_space: null },
];

/** `GET /api/v1/formatprofile` rows (id 1 is the seeded default). */
export const mockFormatProfiles: FormatProfileResource[] = [
  { id: 1, name: 'Standard', formats: ['cbz', 'cbr'], cutoff: 'cbz' },
  { id: 2, name: 'CBZ Only', formats: ['cbz'], cutoff: 'cbz' },
];

export function makeCommand(overrides: Partial<CommandResource> = {}): CommandResource {
  return {
    id: 55,
    name: 'refresh-series',
    status: 'started',
    queued_at: '2026-07-05T12:00:00Z',
    started_at: '2026-07-05T12:00:01Z',
    finished_at: null,
    result: null,
    error: null,
    ...overrides,
  };
}

/** One manual-import candidate exactly as GET /api/v1/manual-import serializes it. */
export function makeManualEntry(
  overrides: Partial<ManualImportEntry> & Pick<ManualImportEntry, 'path'>,
): ManualImportEntry {
  return {
    name: overrides.path.split('/').pop() ?? overrides.path,
    size: 52_428_800,
    folder: null,
    approved: false,
    rejections: [],
    suggestedSeriesId: null,
    suggestedIssueId: null,
    format: null,
    embedded: { comicInfoPresent: false, cvIssueId: null, verified: false },
    ...overrides,
  };
}

/**
 * A candidate list covering FRG-UI-014: one approved row with a verified
 * embedded-ComicInfo suggestion, one blocked row whose reasons the overlay must
 * render verbatim and which becomes importable after an override.
 */
export const mockManualCandidates: ManualImportEntry[] = [
  makeManualEntry({
    path: '/comics/Invincible (2003)/Invincible 001.cbz',
    approved: true,
    suggestedSeriesId: 7,
    suggestedIssueId: 71,
    format: 'cbz',
    embedded: { comicInfoPresent: true, cvIssueId: 6071, verified: true },
  }),
  makeManualEntry({
    path: '/comics/_unsorted/mystery 002.cbr',
    approved: false,
    rejections: ['No series match for parsed title', 'Unmapped issue number'],
    format: 'cbr',
  }),
];

/**
 * One staged library-import group exactly as GET /api/v1/library-import
 * serializes it (the pinned camelCase wire contract).
 */
export function makeLibraryImportGroup(
  overrides: Partial<LibraryImportGroup> & Pick<LibraryImportGroup, 'id'>,
): LibraryImportGroup {
  const id = overrides.id;
  return {
    matchingKey: `series ${id}`,
    folder: `/comics/Series ${id}`,
    files: [
      {
        path: `/comics/Series ${id}/Series ${id} 001.cbz`,
        name: `Series ${id} 001.cbz`,
        size: 25_000_000,
      },
      {
        path: `/comics/Series ${id}/Series ${id} 002.cbz`,
        name: `Series ${id} 002.cbz`,
        size: 26_000_000,
      },
    ],
    confidence: 0.9,
    proposedCvVolumeId: 40501234,
    confirmedCvVolumeId: null,
    state: 'proposed',
    name: 'Saga',
    startYear: 2012,
    publisher: 'Image',
    imageUrl: null,
    rejections: [],
    message: null,
    ...overrides,
  };
}

/*
 * ---------------------------------------------------------------------------
 * Daily-surfaces mocks (m2-daily-surfaces: FRG-UI-010/011/017) — camelCase
 * wire records like the queue's, in the shared ApiPage envelope via pageOf().
 * ---------------------------------------------------------------------------
 */

/** One GET /api/v1/history record with sensible defaults; override per test. */
export function makeHistoryRecord(
  overrides: Partial<HistoryRecord> & Pick<HistoryRecord, 'id'>,
): HistoryRecord {
  return {
    eventType: 'imported',
    sourceTitle: 'Saga 041 (2017) (Digital)',
    downloadId: `SABnzbd_nzo_${overrides.id}`,
    date: '2026-07-05T12:00:00Z',
    data: {},
    series: { id: 1, title: 'Saga' },
    issue: { id: 411, issueNumber: '41', title: 'Chapter Forty-One' },
    ...overrides,
  };
}

/** One GET /api/v1/wanted/missing record; override per test. */
export function makeWantedRecord(
  overrides: Partial<WantedIssueRecord> & Pick<WantedIssueRecord, 'id'>,
): WantedIssueRecord {
  return {
    series_id: 1,
    cv_issue_id: 900041,
    issue_number: '41',
    title: 'Chapter Forty-One',
    cover_date: '2017-01-31',
    store_date: '2017-01-25',
    issue_type: 'issue',
    monitored: true,
    series: { id: 1, title: 'Saga' },
    ...overrides,
  };
}

/** One GET /api/v1/blocklist record; `message` is the verbatim ban reason. */
export function makeBlocklistRecord(
  overrides: Partial<BlocklistRecord> & Pick<BlocklistRecord, 'id'>,
): BlocklistRecord {
  return {
    sourceTitle: 'Saga 041 scanned',
    indexer: 'DogNZB',
    guid: 'guid-41',
    downloadId: 'dl-41',
    date: '2026-07-04T09:00:00Z',
    message: 'Download failed: archive is corrupt',
    protocol: 'usenet',
    series: { id: 1, title: 'Saga' },
    issue: { id: 411, issueNumber: '41', title: null },
    ...overrides,
  };
}

/** GET /api/v1/config/mediamanagement with a recycle bin configured. */
export function makeMediaManagementConfig(
  overrides: Partial<MediaManagementConfig> = {},
): MediaManagementConfig {
  return {
    import_transfer_mode: 'move',
    library_import_mode: 'in_place',
    recycle_bin_path: '/recycle',
    recycle_bin_retention_days: 7,
    duplicate_constraint: 'larger-size',
    duplicate_dump_path: '',
    library_import_proposal_cap: 25,
    library_import_similarity_floor: 0.6,
    ...overrides,
  };
}

export const mockSeriesCreated: SeriesCreatedResource = {
  ...makeSeriesResource({
    id: 42,
    title: 'Saga',
    sort_title: 'saga',
    cv_volume_id: 40501234,
    publisher: 'Image',
    start_year: 2012,
    path: '/comics/Saga (2012)',
    statistics: makeStats({ issue_count: 0, file_count: 0, missing_count: 0, size_on_disk: 0 }),
  }),
  refresh_command_id: 55,
};

/*
 * System area (FRG-UI-016 / FRG-API-014 / FRG-NFR-011) — m2-ops-health-backups.
 */

/** GET /api/v1/system/status — a healthy, fully-populated status (no secret fields). */
export function makeSystemStatus(
  overrides: Partial<SystemStatusResource> = {},
): SystemStatusResource {
  return {
    version: '0.2.5',
    commit: '077833d',
    build_date: '2026-07-06T00:00:00Z',
    config_dir: '/config',
    db_path: '/config/foragerr.db',
    backups_dir: '/config/backups',
    root_folder_count: 2,
    uptime_seconds: 3_600 * 5,
    python_version: '3.12.4',
    os: 'Linux',
    ...overrides,
  };
}

/** One GET /api/v1/health warnings-list entry. */
export function makeHealthWarning(
  overrides: Partial<HealthWarningItem> & Pick<HealthWarningItem, 'source'>,
): HealthWarningItem {
  return {
    type: 'warning',
    message: 'Indexer is disabled after repeated failures.',
    remediationHint: 'Check the indexer credentials and try again.',
    ...overrides,
  };
}

/**
 * One GET /api/v1/system/health per-component row. `component` and `label`
 * are both required overrides (no default) — the real service always emits
 * a hyphenated `kind:numeric-id` machine id (e.g. "indexer:3") alongside a
 * distinct human-readable label (e.g. "Indexer: DogNZB"), and a mock that
 * defaulted `label` risks silently drifting back to the machine id.
 *
 * `last_success` is deliberately offset-LESS ("...T12:00:00", no 'Z') —
 * that is the REAL wire shape: `HealthService`/`ComponentHealth` timestamps
 * come from the app's naive-UTC `utcnow()` (backend/src/foragerr/db/base.py),
 * and Pydantic v2 serializes a naive datetime without a trailing 'Z' or
 * offset. A mock that added 'Z' would hide the FRG-API-014 UTC-parsing bug
 * the fixed `asUtcIso` helper in lib/format.ts exists to handle.
 */
export function makeHealthComponent(
  overrides: Partial<SystemHealthComponent> &
    Pick<SystemHealthComponent, 'component' | 'label'>,
): SystemHealthComponent {
  return {
    state: 'ok',
    message: null,
    last_success: '2026-07-06T12:00:00',
    last_failure: null,
    disabled_until: null,
    ...overrides,
  };
}

/**
 * GET /api/v1/system/health for an all-healthy system, one row per component
 * area — machine ids and labels match the real `HealthService` shapes
 * (backend/src/foragerr/health/service.py): hyphenated `kind:numeric-id`
 * ids, distinct human-readable labels.
 */
export const mockHealthyComponents: SystemHealthComponent[] = [
  makeHealthComponent({ component: 'comicvine', label: 'ComicVine' }),
  makeHealthComponent({ component: 'indexer:3', label: 'Indexer: DogNZB' }),
  makeHealthComponent({
    component: 'download-client:1',
    label: 'Download client: SABnzbd',
  }),
  makeHealthComponent({ component: 'scheduler', label: 'Scheduler' }),
  makeHealthComponent({ component: 'database', label: 'Database' }),
  makeHealthComponent({ component: 'root-folder:1', label: 'Root folder: /comics' }),
  makeHealthComponent({ component: 'disk-space', label: 'Config volume free space' }),
];

/**
 * One GET /api/v1/system/task row. `last_run`/`next_run` are deliberately
 * offset-LESS ("...T03:00:00", no 'Z') — the real `ScheduledTask` timestamps
 * come from the naive-UTC `utcnow()` (backend/src/foragerr/db/base.py), and
 * Pydantic v2 serializes a naive datetime without a trailing 'Z' or offset.
 * See `makeHealthComponent` for the same rationale.
 */
export function makeScheduledTask(
  overrides: Partial<ScheduledTaskResource> & Pick<ScheduledTaskResource, 'name'>,
): ScheduledTaskResource {
  return {
    command_name: overrides.name,
    label: overrides.name,
    interval_seconds: 86_400,
    last_run: '2026-07-05T03:00:00',
    next_run: '2026-07-06T03:00:00',
    ...overrides,
  };
}
