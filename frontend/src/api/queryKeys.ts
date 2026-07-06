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
 *   ['rootfolder']          <-> GET /api/v1/rootfolder
 *   ['formatprofile']       <-> GET /api/v1/formatprofile
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
  // Paged daily surfaces (FRG-UI-010/011/017), family-page convention like
  // ['queue', page] plus a filters hash so two filterings of the same page are
  // distinct cache entries: ['history', 2, 'eventType=imported']. Invalidating
  // the bare family key sweeps every page/filter combination.
  history: {
    all: () => ['history'] as const,
    page: (page: number, filtersHash = '') =>
      ['history', page, filtersHash] as const,
  },
  wanted: {
    all: () => ['wanted'] as const,
    page: (page: number, filtersHash = '') =>
      ['wanted', page, filtersHash] as const,
  },
  blocklist: {
    all: () => ['blocklist'] as const,
    page: (page: number, filtersHash = '') =>
      ['blocklist', page, filtersHash] as const,
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
  rootFolder: {
    all: () => ['rootfolder'] as const,
  },
  // Config singletons (FRG-API-013) + the shared token vocabulary (FRG-UI-012),
  // mirroring GET /api/v1/config/{naming,mediamanagement,naming/tokens}.
  //
  // The token vocabulary is deliberately keyed OUTSIDE the ['config','naming']
  // prefix (as ['config','namingTokens']) even though its URL nests under it:
  // the tokens query carries staleTime Infinity (it is a property of the build's
  // renderer, never refetched), so a future broad invalidation of the naming
  // config — invalidateQueries(['config','naming']) after a PUT — must NOT sweep
  // it up by prefix and force a refetch of the static vocabulary.
  config: {
    naming: () => ['config', 'naming'] as const,
    mediaManagement: () => ['config', 'mediamanagement'] as const,
    namingTokens: () => ['config', 'namingTokens'] as const,
  },
  // Per-series rename preview (FRG-PP-012), mirroring GET /api/v1/rename.
  rename: {
    forSeries: (seriesId: number) => ['rename', seriesId] as const,
  },
  // Manual-import candidate list (FRG-UI-014), mirroring the mutually-exclusive
  // GET /api/v1/manual-import?path= XOR ?downloadId=. Keyed by its single source
  // so the overlay refetches exactly that source after a manual-import command.
  manualImport: {
    forPath: (path: string) => ['manual-import', 'path', path] as const,
    forDownload: (downloadId: string) =>
      ['manual-import', 'download', downloadId] as const,
  },
  formatProfile: {
    all: () => ['formatprofile'] as const,
  },
  // Library-import staging groups (FRG-UI-015), mirroring the source-keyed
  // GET /api/v1/library-import?rootFolderId=. Keyed per root folder so a scan
  // or execute command invalidates exactly the root it staged.
  libraryImport: {
    all: () => ['library-import'] as const,
    forRoot: (rootFolderId: number) =>
      ['library-import', rootFolderId] as const,
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
