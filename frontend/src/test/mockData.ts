import type { Series, SeriesDetail, QueueItem, ReleaseDecision } from '../api/types';

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
