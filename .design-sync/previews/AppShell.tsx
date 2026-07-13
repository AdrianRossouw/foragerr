import { AppShell, PreviewData } from 'foragerr-frontend';

/**
 * The whole Sonarr-style chrome: 212px sidebar (nav + live badges + status
 * footer) and the 60px global header (relocated quick-search on the left,
 * health/system/logout icon buttons on the right). The content region is
 * AppShell's `<Outlet />`; in a preview there is no nested route to fill it,
 * so the main column reads empty by design — this preview is the FRAME. The
 * sidebar/header are fed the same caches the app uses via PreviewData.
 *
 * Wide component: if the capture clips in its grid cell, apply the single-card
 * override recorded in learnings/shell.md.
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
  queue: { page: 1, pageSize: 1, sortKey: 's', sortDirection: 'asc', totalRecords: 3, records: [] },
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

/** The framed application shell with a populated sidebar + header. */
export const Shell = () => (
  <PreviewData responses={responses}>
    <div style={{ height: 700, display: 'flex' }}>
      <AppShell />
    </div>
  </PreviewData>
);
