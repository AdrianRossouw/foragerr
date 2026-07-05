/*
 * Query-key factory (FRG-UI-001).
 *
 * Keys MIRROR API resource paths so cache identity and URL identity never drift:
 *   ['series']              <-> GET /api/v1/series
 *   ['series', id]          <-> GET /api/v1/series/{id}
 *   ['queue', page]         <-> GET /api/v1/queue?page={page}
 *   ['release', issueId]    <-> GET /api/v1/release?issueId={issueId}
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
    page: (page: number) => ['queue', page] as const,
  },
  release: {
    forIssue: (issueId: number) => ['release', issueId] as const,
  },
} as const;

export type SeriesListKey = ReturnType<typeof queryKeys.series.all>;
export type SeriesDetailKey = ReturnType<typeof queryKeys.series.detail>;
export type QueuePageKey = ReturnType<typeof queryKeys.queue.page>;
export type ReleaseKey = ReturnType<typeof queryKeys.release.forIssue>;
