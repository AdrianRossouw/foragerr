/*
 * Query-key factory (FRG-UI-001).
 *
 * Keys MIRROR API resource paths so cache identity and URL identity never drift:
 *   ['series']              <-> GET /api/v1/series
 *   ['series', id]          <-> GET /api/v1/series/{id}
 *   ['queue', page]         <-> GET /api/v1/queue?page={page}
 *   ['release', issueId]    <-> GET /api/v1/release?issueId={issueId}
 *   [kind]                  <-> GET /api/v1/{kind}         (provider rows)
 *   [kind, 'schema']        <-> GET /api/v1/{kind}/schema  (kind = 'indexer'
 *                                                          | 'downloadclient')
 *
 * The WebSocketBridge and every screen invalidate/patch through these helpers —
 * no raw array literals in components.
 */
export const queryKeys = {
  series: {
    all: () => ['series'] as const,
    detail: (id: number) => ['series', id] as const,
  },
  queue: {
    all: () => ['queue'] as const,
    page: (page: number) => ['queue', page] as const,
  },
  release: {
    forIssue: (issueId: number) => ['release', issueId] as const,
  },
  provider: {
    all: (kind: string) => [kind] as const,
    schema: (kind: string) => [kind, 'schema'] as const,
  },
  issues: {
    forSeries: (seriesId: number) => ['issues', seriesId] as const,
  },
  command: {
    all: () => ['command'] as const,
    detail: (id: number) => ['command', id] as const,
  },
  // ComicVine lookup deliberately does NOT live under the ['series'] prefix
  // (its path is /api/v1/series/lookup): the WebSocketBridge invalidates
  // ['series'] on every series push, and a prefix-matched lookup query would
  // refetch against live ComicVine (rate-limited) on each push while the add
  // screen is open.
  lookup: {
    term: (term: string) => ['lookup', term] as const,
  },
} as const;

export type SeriesListKey = ReturnType<typeof queryKeys.series.all>;
export type SeriesDetailKey = ReturnType<typeof queryKeys.series.detail>;
export type QueuePageKey = ReturnType<typeof queryKeys.queue.page>;
export type ReleaseKey = ReturnType<typeof queryKeys.release.forIssue>;
