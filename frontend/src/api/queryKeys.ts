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
    // Franchise grouping projection (FRG-API-020), mirroring GET
    // /api/v1/series/groups. Nested under the ['series'] prefix so a broad,
    // id-less series push (WebSocketBridge) sweeps it too — groups are derived
    // from series, and (unlike ComicVine lookup) refetching them is cheap. The
    // exact-match ['series'] invalidations that back the flat index never touch
    // it; a group edit invalidates this key explicitly.
    groups: () => ['series', 'groups'] as const,
    // Declared collections for one series (FRG-API-022), mirroring GET
    // /api/v1/series/{id}/collections. Nested under the ['series', id] prefix so
    // a broad series-detail invalidation sweeps it, while the exact-match
    // ['series'] index invalidation (and the setQueryData on ['series', id])
    // leave it untouched — a plain monitor toggle never refetches collections.
    collections: (id: number) => ['series', id, 'collections'] as const,
  },
  queue: {
    all: () => ['queue'] as const,
    page: (page: number) => ['queue', page] as const,
    // Total tracked-download count for the sidebar Activity badge (FRG-UI-023).
    // Nested under the ['queue'] prefix so the WebSocketBridge's queue
    // invalidation (queryKeys.queue.all()) sweeps it with no separate wiring.
    count: () => ['queue', 'count'] as const,
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
  // Weekly pull / calendar projection (FRG-API-019), mirroring GET
  // /api/v1/pull?week=. One cache entry per ISO week (the screen always loads
  // the whole week — day-grouping/counts are whole-week properties, design
  // decision 1). The WebSocketBridge and per-entry actions invalidate the bare
  // family key (`pull.all()`) so every loaded week re-derives its card state.
  pull: {
    all: () => ['pull'] as const,
    week: (week: string) => ['pull', week] as const,
  },
  blocklist: {
    all: () => ['blocklist'] as const,
    page: (page: number, filtersHash = '') =>
      ['blocklist', page, filtersHash] as const,
  },
  // Log ring buffer (FRG-UI-024), mirroring GET /api/v1/log. Same
  // family-page-filtersHash convention as history/wanted/blocklist; the
  // filters hash includes the minimum-level and logger-prefix filters so
  // each filtering is its own cache entry.
  log: {
    all: () => ['log'] as const,
    page: (page: number, filtersHash = '') =>
      ['log', page, filtersHash] as const,
  },
  release: {
    forIssue: (issueId: number) => ['release', issueId] as const,
  },
  provider: {
    all: (kind: string) => [kind] as const,
    schema: (kind: string) => [kind, 'schema'] as const,
  },
  issues: {
    // Prefix, used by the WebSocketBridge's id-less series-push fallback: an
    // id-less push can't target one series' issues, so it sweeps every open
    // issues table rather than stranding one it can't identify.
    all: () => ['issues'] as const,
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
    // The ComicVine credential settings resource (FRG-API-018), mirroring
    // GET/PUT /api/v1/config/general. A successful PUT replaces this cache
    // entry directly (`setQueryData`), which is what "invalidates" the
    // credential status for any screen reading it next.
    general: () => ['config', 'general'] as const,
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
    // Suggest (FRG-API-017) is a SEPARATE cache family from the full lookup
    // above, even though both key off `term`: it is a different envelope
    // shape ({records, complete} — no `truncated`) and a different endpoint,
    // so a term that has both a full-lookup and a suggest entry never
    // collides or cross-invalidates.
    suggest: (term: string) => ['lookup', 'suggest', term] as const,
  },
  // System area (FRG-UI-016 / FRG-API-014 / FRG-NFR-011), mirroring
  // GET /api/v1/system/{status,health,task}.
  system: {
    status: () => ['system', 'status'] as const,
    health: () => ['system', 'health'] as const,
    tasks: () => ['system', 'task'] as const,
  },
  // Creators surface (FRG-UI-027/028 / FRG-API-023/024), mirroring
  //   ['creators', 'list', hash]          <-> GET /api/v1/creators?<params>
  //   ['creators', id]                    <-> GET /api/v1/creators/{id}
  //   ['creators', 'bibliography', id]    <-> GET /api/v1/creators/{id}/bibliography
  // The list family is keyed by a params hash (followed/seriesId/sort) so each
  // filtering + focus is its own cache entry; the follow toggle invalidates the
  // bare family key (`creators.all()`) so every loaded grid/profile re-derives.
  // 'list'/'bibliography' (strings) and the numeric id never collide under the
  // prefix. Bibliography lives under its OWN 'bibliography' sub-prefix so the WS
  // command-completion invalidation (`bibliographyAll()`) sweeps every loaded
  // bibliography without touching the grids/profiles — the WS command payload
  // carries no creator id, so it can only invalidate the family, not one row.
  creators: {
    all: () => ['creators'] as const,
    list: (paramsHash: string) => ['creators', 'list', paramsHash] as const,
    detail: (id: number) => ['creators', id] as const,
    bibliography: (id: number) => ['creators', 'bibliography', id] as const,
    bibliographyAll: () => ['creators', 'bibliography'] as const,
  },
  // The actionable warnings list is deliberately its OWN top-level family
  // (not nested under `system`): it mirrors GET /api/v1/health, distinct from
  // both the root liveness `/health` (no query key — never fetched via React
  // Query) and GET /api/v1/system/health above (design decision 5).
  health: {
    warnings: () => ['health'] as const,
  },
  // Store sources (FRG-UI-029 / FRG-SRC-*), mirroring
  //   ['sources']                                   <-> GET /api/v1/sources
  //   ['sources', id, 'entitlements', hash]         <-> GET /sources/{id}/entitlements
  //   ['sources', 'entitlement', id]                <-> GET /sources/entitlements/{id}
  //   ['sources', 'new-count', idsHash]             <-> aggregated new-review count
  // The list key is the bare ['sources'] prefix, so a review action / sync /
  // connect that invalidates `sources.all()` sweeps the list, every source's
  // entitlement queries, an open entitlement detail, AND the sidebar new-count
  // in one call (the whole inventory re-derives together). 'entitlement' and
  // 'new-count' (strings) never collide with a numeric source id under the prefix.
  sources: {
    all: () => ['sources'] as const,
    list: () => ['sources'] as const,
    entitlements: (sourceId: number, filtersHash = '') =>
      ['sources', sourceId, 'entitlements', filtersHash] as const,
    entitlementDetail: (id: number) => ['sources', 'entitlement', id] as const,
    newCount: (idsHash: string) => ['sources', 'new-count', idsHash] as const,
  },
  // Auth (m8-auth-core, FRG-AUTH-002), mirroring GET /api/v1/auth/me. A
  // singleton — not invalidated by the WebSocketBridge (no server push exists
  // for session state); `AuthGate` re-derives the client auth store from it
  // directly rather than reading this cache elsewhere.
  auth: {
    me: () => ['auth', 'me'] as const,
  },
} as const;

export type SeriesListKey = ReturnType<typeof queryKeys.series.all>;
export type SeriesDetailKey = ReturnType<typeof queryKeys.series.detail>;
export type QueuePageKey = ReturnType<typeof queryKeys.queue.page>;
export type ReleaseKey = ReturnType<typeof queryKeys.release.forIssue>;
