import type {
  Series,
  SeriesDetail,
  QueuePageResponse,
  QueueResourceRaw,
  ReleaseDecision,
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
