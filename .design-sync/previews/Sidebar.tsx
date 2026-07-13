import { Sidebar, PreviewData } from 'foragerr-frontend';

/**
 * Full nav rail with live count badges fed off the same caches the app reads:
 * Comics = library size, Wanted = series-with-missing (amber), Queue =
 * tracked downloads, Sources = unreviewed-`new` count (amber). Footer carries
 * the running version + health line.
 *
 * Fixture-path notes: `entitlements` is keyed BEFORE `sources` because the
 * per-source new-count path (`/sources/{id}/entitlements?...`) also contains
 * "sources" — first substring match wins, so the more specific key leads. The
 * connection store defaults to `connecting` in a preview (no live socket), so
 * the footer honestly reads "reconnecting…" with the connecting dot.
 */
const series = [
  { id: 1, title: 'Saga', statistics: { missing_count: 4 } },
  { id: 2, title: 'Monstress', statistics: { missing_count: 0 } },
  { id: 3, title: 'The Wicked + The Divine', statistics: { missing_count: 2 } },
  { id: 4, title: 'Invincible', statistics: { missing_count: 0 } },
  { id: 5, title: 'Paper Girls', statistics: { missing_count: 0 } },
];

const responses = {
  entitlements: [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }, { id: 5 }, { id: 6 }, { id: 7 }],
  'series?': {
    page: 1,
    pageSize: 200,
    sortKey: 'sort_title',
    sortDirection: 'asc',
    totalRecords: series.length,
    records: series,
  },
  queue: {
    page: 1,
    pageSize: 1,
    sortKey: 's',
    sortDirection: 'asc',
    totalRecords: 3,
    records: [],
  },
  'system/status': { version: '1.4.2' },
  health: [],
  sources: [
    {
      id: 5,
      type: 'humble',
      name: 'Humble Bundle',
      connection_state: 'connected',
      auto_sync: false,
      last_sync_status: 'ok',
      settings: {},
    },
  ],
};

/** Populated rail: library of 5 (2 wanted), 3 queued, 7 unreviewed source items. */
export const Populated = () => (
  <PreviewData responses={responses}>
    <div style={{ height: 620, display: 'flex' }}>
      <Sidebar />
    </div>
  </PreviewData>
);

/**
 * Clean first-run install: no library, no sources — a badge-free rail. The
 * empty `series?` envelope is still explicit (the series index reads
 * `.records`, so the bare `[]` stub would throw).
 */
export const Empty = () => (
  <PreviewData
    responses={{
      'series?': {
        page: 1,
        pageSize: 200,
        sortKey: 'sort_title',
        sortDirection: 'asc',
        totalRecords: 0,
        records: [],
      },
      queue: { page: 1, pageSize: 1, sortKey: 's', sortDirection: 'asc', totalRecords: 0, records: [] },
      'system/status': { version: '1.4.2' },
      health: [],
      sources: [],
    }}
  >
    <div style={{ height: 620, display: 'flex' }}>
      <Sidebar />
    </div>
  </PreviewData>
);
