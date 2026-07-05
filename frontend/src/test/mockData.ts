import type {
  ApiPage,
  CommandResource,
  IssueResource,
  LookupCandidate,
  QueueItem,
  ReleaseDecision,
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

export const mockQueuePage1: QueueItem[] = [
  {
    id: 900,
    title: 'Saga 041',
    status: 'downloading',
    progress: 10,
    size: 100,
    sizeLeft: 90,
  },
  {
    id: 901,
    title: 'Saga 042',
    status: 'downloading',
    progress: 25,
    size: 100,
    sizeLeft: 75,
  },
];

export const mockReleases: ReleaseDecision[] = [
  {
    cacheKey: 'abc123',
    indexer: 'DogNZB',
    title: 'Saga 041 (2017)',
    size: 42_000_000,
    ageDays: 3,
    approved: true,
    score: 120,
    rejections: [],
  },
  {
    cacheKey: 'def456',
    indexer: 'NZB.su',
    title: 'Saga 041 scanned',
    size: 12_000_000,
    ageDays: 900,
    approved: false,
    score: -5,
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
    name_similarity: 0.42,
    year_proximity: 30,
    target_issue_plausible: false,
    have_it: true,
  },
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
