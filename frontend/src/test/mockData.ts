import type {
  ApiPage,
  CommandResource,
  FormatProfileResource,
  IssueResource,
  LibraryImportGroup,
  LookupCandidate,
  ManualImportEntry,
  QueuePageResponse,
  QueueResourceRaw,
  ReleaseDecision,
  RootFolderResource,
  Series,
  SeriesCreatedResource,
  SeriesDetail,
  SeriesResource,
  SeriesStatisticsResource,
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
 * One staged library-import group as GET /api/v1/library-import serializes it
 * (already in the UI's normalized camelCase shape; the snake_case tolerance is
 * covered by a dedicated test feeding raw snake_case keys).
 */
export function makeLibraryImportGroup(
  overrides: Partial<LibraryImportGroup> & Pick<LibraryImportGroup, 'id'>,
): LibraryImportGroup {
  const id = overrides.id;
  return {
    matchingKey: `series ${id}`,
    folder: `/comics/Series ${id}`,
    files: [
      `/comics/Series ${id}/Series ${id} 001.cbz`,
      `/comics/Series ${id}/Series ${id} 002.cbz`,
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
