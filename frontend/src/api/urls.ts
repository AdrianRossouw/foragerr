/*
 * Shared API URL builders (FRG-UI-003/004).
 *
 * The library index and the series detail screen both point posters at the
 * LOCAL cover-cache endpoint — never an external ComicVine host. Keeping the
 * literal in one place stops the two call sites from drifting apart.
 */

/**
 * Local cover-cache endpoint for a series poster, versioned by
 * `cover_cached_at`.
 *
 * A constant URL is wrong on two counts: (1) if the first render lands
 * before the backend has cached the cover, the `<img>` 404s once and the
 * browser never retries that exact src — a later WS-driven refetch re-renders
 * the same element with the same unchanged src, so the broken image sticks
 * until a hard reload; (2) when a refresh replaces the cached art, the byte
 * content changes but the URL doesn't, so neither React nor the HTTP cache
 * has a reason to re-fetch it. Appending `cover_cached_at` as `?v=` gives the
 * `<img>` a new src whenever the cache state changes — null (no cover yet) to
 * a timestamp, or one timestamp to a newer one — which busts both the failed
 * -load state and any HTTP caching. Returning `null` when there is no cached
 * cover yet avoids emitting a URL that is known to 404.
 */
export function coverUrl(
  series: { id: number; cover_cached_at: string | null },
): string | null {
  if (series.cover_cached_at == null) return null;
  return `/api/v1/series/${series.id}/cover?v=${encodeURIComponent(series.cover_cached_at)}`;
}

/**
 * Same-origin proxy URL for a CANDIDATE cover (FRG-META-021) — lookup and
 * review surfaces get their `image_url` from ComicVine, and the SPA's
 * self-contained CSP (`img-src 'self'`, FRG-SEC-006) rightly blocks a direct
 * hotlink. The backend proxies allowlisted CV media hosts; anything else
 * (or null) renders the poster fallback instead of a blocked request.
 */
export function candidateCoverUrl(imageUrl: string | null | undefined): string | null {
  if (!imageUrl) return null;
  return `/api/v1/metadata/cover?src=${encodeURIComponent(imageUrl)}`;
}
